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

from ai.openai_model import from_env
from ai.openai_model import stream as openai_stream
from ai.types import ModelContext
from coding_agent.render import DIM, RESET, TerminalRenderer
from coding_agent.session import CodingSession


class ProviderAdapter:
    """把 ai.openai_model.stream(client, model, ctx) 适配成 Agent 期望的 provider 协议。

    组装发生在 CLI 层（02-architecture：CLI 负责组装适配器），session 层不接触 SDK。
    """

    def __init__(self, client, model) -> None:
        self._client = client
        self._model = model

    async def stream(self, context: ModelContext):
        async for event in openai_stream(self._client, self._model, context):
            yield event


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="A minimal Python coding agent")
    parser.add_argument("prompt", nargs="*", help="可选：单次执行的任务描述；省略则进入交互模式")
    parser.add_argument("--workspace", default=".", help="工作区根目录（默认当前目录）")
    parser.add_argument("--max-turns", type=int, default=20, help="每个用户输入的 Agent 轮数上限（默认 20）")
    parser.add_argument("--no-color", action="store_true", help="禁用 ANSI 颜色")
    return parser.parse_args()


def _banner(session: CodingSession, model_id: str, max_turns: int) -> None:
    """一次性欢迎横幅。"""

    line = "─" * 62
    print(f"{DIM}{line}{RESET}")
    print(f" pi-study · 工作区 {session.workspace.root}")
    print(f" 模型 {model_id} · 轮数上限 {max_turns}")
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


async def _cancel_child(session: CodingSession, task: asyncio.Task) -> None:
    session.cancel()  # 协作式取消信号（工具/轮间检查）
    task.cancel()  # 任务级取消（模型流中也能停）
    try:
        await task
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass


async def async_main() -> int:
    load_dotenv()
    args = parse_args()

    try:
        client, model = from_env()
    except RuntimeError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2

    session = CodingSession(
        provider=ProviderAdapter(client, model),
        model=model,
        root=Path(args.workspace),
        max_turns=args.max_turns,
    )
    session.agent.subscribe(TerminalRenderer(color=not args.no_color))

    prompt = " ".join(args.prompt).strip()
    if prompt:
        _banner(session, model.id, args.max_turns)
        await _run_prompt(session, prompt)
        return 0

    _banner(session, model.id, args.max_turns)
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
        await _run_prompt(session, user_input)
    return 0


def _raise_keyboard_interrupt(signum, frame) -> None:  # noqa: ARG001
    raise KeyboardInterrupt


def main() -> None:
    # 在 asyncio.run 之前接管 SIGINT：runner 只会接管默认处理器；
    # 我们的处理器直接抛 KeyboardInterrupt，使 Ctrl+C 语义可控。
    signal.signal(signal.SIGINT, _raise_keyboard_interrupt)
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        # 在事件循环调度/收尾阶段到达的 Ctrl+C：视为正常退出（第二次 Ctrl+C）
        pass
    raise SystemExit(0)
