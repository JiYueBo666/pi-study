"""CLI 入口 — 组装适配器并启动 Coding Agent。

02-architecture：CLI 位于 coding_agent，负责组装 Coding 产品（Provider 适配、
工作区、事件渲染）。CLI 只消费 Agent 事件，不窥探 Agent 状态。

Ctrl+C 语义（03-contracts §4）：
- 运行中第一次 Ctrl+C：取消活动轮次，会话回到 idle；
- idle 状态下第二次 Ctrl+C：退出程序。
"""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from agent_core.session.jsonl import JsonlSessionStore
from agent_core.session.types import SessionError
from ai.openai_model import from_env
from coding_agent.commands import (
    CommandContext,
    CommandRegistry,
    register_builtin_commands,
)
from coding_agent.event import ToolApprovalRequested
from coding_agent.provider import ProviderAdapter
from coding_agent.render import DIM, RESET, TerminalRenderer
from coding_agent.session import CodingSession


def _approval_listener(session: CodingSession):
    """为终端 CLI 提供审批交互，避免 ASK 模式下无人解析 Future。"""

    def listener(event: object) -> None:
        if not isinstance(event, ToolApprovalRequested):
            return

        request = event.request
        print(f"\n工具调用需要审批: {request.tool_name}")
        print(f"说明: {request.tool_description}")
        print(f"参数: {request.call.arguments}")

        while True:
            answer = input("允许执行？[y/n] ").strip().lower()
            if answer in {"y", "yes", "n", "no"}:
                approved = answer in {"y", "yes"}
                session.resolve_tool_approval(request.request_id, approved)
                return
            print("请输入 y 或 n")

    return listener


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A minimal Python coding agent")
    parser.add_argument("prompt", nargs="*", help="可选：单次执行的任务描述；省略则进入交互模式")
    parser.add_argument("--workspace", default=".", help="工作区根目录（默认当前目录）")
    parser.add_argument(
        "--max-turns",
        type=int,
        default=20,
        help="每个用户输入的 Agent 轮数上限（默认 20）",
    )
    parser.add_argument("--no-color", action="store_true", help="禁用 ANSI 颜色")
    parser.add_argument("--resume", metavar="SESSION_ID", help="恢复指定会话（支持唯一前缀）")
    parser.add_argument("--list-sessions", action="store_true", help="列出当前工作区可用会话")
    parser.add_argument("--forget", metavar="SESSION_ID", help="删除指定会话")
    return parser.parse_args()


def _banner(session: CodingSession, model_id: str, max_turns: int) -> None:
    """一次性欢迎横幅。"""

    line = "─" * 62
    session_label = session.session_id or "新会话"
    print(f"{DIM}{line}{RESET}")
    print(f" pi-study · 工作区 {session.workspace.root}")
    print(f" 会话 {session_label} · 模型 {model_id} · 轮数上限 {max_turns}")
    print(" 输入任务；Ctrl+C 取消当前任务，idle 时再按一次退出")
    print(f"{DIM}{line}{RESET}")


async def _run_prompt(session: CodingSession, user_input: str) -> None:
    """执行一个任务，处理运行中的 Ctrl+C（第一次：取消并回 idle）。"""

    task = asyncio.create_task(session.prompt(user_input))
    try:
        await task
    except KeyboardInterrupt:
        # 自定义 SIGINT 处理器：以 KeyboardInterrupt 到达
        await _cancel_child(session, task)
        print("\n[cancelled — 已取消，可继续输入]")
    except asyncio.CancelledError:
        # 未安装自定义处理器时，asyncio.run 会以取消主任务的方式投递 SIGINT
        await _cancel_child(session, task)
        print("\n[cancelled — 已取消，可继续输入]")
    finally:
        # 无论成功、失败还是取消，都把当前历史持久化，避免丢失对话
        try:
            session.save()
        except Exception as exc:
            print(f"[warning] 保存会话失败: {exc}", file=sys.stderr)


async def _cancel_child(session: CodingSession, task: asyncio.Task) -> None:
    session.cancel()  # 协作式取消信号（工具/轮间检查）
    task.cancel()  # 任务级取消（模型流中也能停）
    try:
        await task
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass


def _setup_command_completion(registry: CommandRegistry) -> None:
    """配置 readline：/ 命令 Tab 补全 + 补全列表展示。"""

    try:
        import readline
    except ImportError:
        return

    def completer(text: str, state: int) -> str | None:
        line = readline.get_line_buffer()
        # 只在输入第一个词且以 / 开头时补全命令名
        if not line.startswith("/") or " " in line:
            return None
        matches = registry.complete(line)
        if state < len(matches):
            return "/" + matches[state]
        return None

    def display_matches(substitution, matches, longest_match_length) -> None:  # noqa: ARG001
        # readline 会先清空当前行；这里打印一个简单的“弹窗”式补全列表
        print()
        if matches:
            print(f"{DIM}┌─ 命令补全 ─{RESET}")
            for match in matches:
                print(f"{DIM}│ /{match}{RESET}")
            print(f"{DIM}└{'─' * 20}{RESET}")

    readline.set_completer(completer)
    readline.set_completion_display_matches_hook(display_matches)
    readline.parse_and_bind("tab: complete")


async def async_main() -> int:
    load_dotenv()
    args = parse_args()
    workspace = Path(args.workspace).resolve()
    store = JsonlSessionStore(workspace / ".pi-study" / "sessions")

    # 会话管理命令不需要 API Key，提前处理
    if args.list_sessions:
        metas = store.list()
        if not metas:
            print("(no sessions)")
        for meta in metas:
            print(f"{meta.id}  {meta.updated_at:%Y-%m-%d %H:%M:%S}  {meta.message_count} messages  {meta.cwd}")
        return 0

    if args.forget:
        try:
            session_id = store.resolve(args.forget)
            store.delete(session_id)
            print(f"deleted session {session_id}")
        except SessionError as exc:
            print(f"错误: {exc}", file=sys.stderr)
            return 2
        return 0

    resume_meta = None
    resume_messages: list = []
    if args.resume:
        try:
            session_id = store.resolve(args.resume)
            resume_meta, resume_messages = store.load(session_id)
        except SessionError as exc:
            print(f"会话错误: {exc}", file=sys.stderr)
            return 2
        if Path(resume_meta.cwd).resolve() != workspace:
            print(
                f"错误: 会话 {resume_meta.id} 的工作区是 {resume_meta.cwd}，当前工作区是 {workspace}",
                file=sys.stderr,
            )
            return 2

    try:
        client, model = from_env()
    except RuntimeError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    try:
        session = CodingSession(
            provider=ProviderAdapter(client, model),
            model=model,
            root=workspace,
            max_turns=args.max_turns,
            session_id=resume_meta.id if resume_meta else None,
            history=resume_messages if resume_meta else (),
            created_at=resume_meta.created_at if resume_meta else None,
        )
        session.agent.subscribe(TerminalRenderer(color=not args.no_color))
        session.subscribe(_approval_listener(session))

        prompt = " ".join(args.prompt).strip()
        if prompt:
            _banner(session, model.id, args.max_turns)
            await _run_prompt(session, prompt)
            return 0

        _banner(session, model.id, args.max_turns)

        registry = CommandRegistry()
        register_builtin_commands(registry)
        command_context = CommandContext(session=session, session_store=store, workspace=workspace)
        _setup_command_completion(registry)

        while True:
            try:
                # idle 期同步 input：阻塞事件循环无影响（此时没有别的任务），
                # Ctrl+C 由自定义 SIGINT 处理器直接以 KeyboardInterrupt 打断。
                user_input = input("you> ")
            except (EOFError, KeyboardInterrupt):
                # idle 时 Ctrl+C / Ctrl+D：退出
                print()
                break
            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                result = await registry.execute(user_input, command_context)
                if result.message:
                    print(result.message)
                if result.should_exit:
                    break
                continue

            await _run_prompt(session, user_input)
        return 0
    finally:
        # 显式关闭 OpenAI 客户端，避免退出时 httpcore 异步生成器告警
        await client.close()


def _raise_keyboard_interrupt(signum, frame) -> None:  # noqa: ARG001
    raise KeyboardInterrupt


def main() -> None:
    # 在 asyncio.run 之前接管 SIGINT：runner 只会接管默认处理器；
    # 我们的处理器直接抛 KeyboardInterrupt，使 Ctrl+C 语义可控。
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    try:
        code = asyncio.run(async_main())
    except KeyboardInterrupt:
        # 在事件循环调度/收尾阶段到达的 Ctrl+C：视为正常退出（第二次 Ctrl+C）
        code = 0
    raise SystemExit(code)
