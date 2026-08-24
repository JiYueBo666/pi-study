"""内置命令：/quit 等。"""

from agent_core.session.types import SessionError
from coding_agent.commands.base import Command, CommandContext, CommandRegistry, CommandResult


async def _quit(context: CommandContext, args: list[str]) -> CommandResult:
    return CommandResult(message="bye", should_exit=True)


async def _compact(context: CommandContext, args: list[str]) -> CommandResult:
    if context.session is None:
        return CommandResult(message="当前没有会话", status="error")
    summary = await context.session.compact()
    return CommandResult(message=summary)


async def _clear(context: CommandContext, args: list[str]) -> CommandResult:
    if args:
        return CommandResult(message="usage: /clear", status="error")
    return CommandResult(data={"action": "clear"})


async def _model(context: CommandContext, args: list[str]) -> CommandResult:
    if context.session is None:
        return CommandResult(message="当前没有会话", status="error")
    if len(args) > 1:
        return CommandResult(message="usage: /model [model_id]", status="error")
    if not args:
        return CommandResult(message=f"当前模型: {context.session.model.id}")

    try:
        model = context.session.set_model(args[0])
    except ValueError as exc:
        return CommandResult(message=str(exc), status="error")
    return CommandResult(
        message=f"已切换模型: {model.id}",
        data={"action": "model_changed", "model": model.id},
    )


async def _status(context: CommandContext, args: list[str]) -> CommandResult:
    if context.session is None:
        return CommandResult(message="当前没有会话", status="error")
    if args:
        return CommandResult(message="usage: /status", status="error")

    status = context.session.status()
    role_counts = status["role_counts"]
    role_text = ", ".join(f"{role}={count}" for role, count in sorted(role_counts.items())) or "无"
    session_id = status["session_id"] or "新会话"
    compaction = "开启" if status["compaction_enabled"] else "关闭"
    lines = [
        f"会话: {session_id}",
        f"模型: {status['model']}",
        f"工作区: {status['workspace']}",
        f"消息: {status['message_count']} ({role_text})",
        (f"上下文: 约 {status['estimated_tokens']} tokens / {status['compaction_threshold']} 压缩阈值 ({compaction})"),
        f"审批: {status['approval_mode']}，待处理 {status['pending_approvals']}",
    ]
    return CommandResult(message="\n".join(lines), data={"action": "status", **status})


async def _session(context: CommandContext, args: list[str]) -> CommandResult:
    """列出 / 载入 / 删除会话。

    - `/session`：列出全部会话，UI 可弹窗选择
    - `/session <id>`：载入指定会话（支持唯一前缀）
    - `/session delete <id>`：删除指定会话
    """
    store = context.session_store
    if store is None:
        return CommandResult(message="当前没有会话存储", status="error")

    def _session_dict(meta) -> dict:
        return {
            "id": meta.id,
            "cwd": meta.cwd,
            "updated_at": meta.updated_at.isoformat(),
            "message_count": meta.message_count,
        }

    if not args:
        metas = store.list()
        sessions = [_session_dict(m) for m in metas]
        if not sessions:
            return CommandResult(message="(no sessions)", data={"action": "list", "sessions": sessions})
        lines = [f"{s['id']}  {s['updated_at']}  {s['message_count']} messages  {s['cwd']}" for s in sessions]
        return CommandResult(message="\n".join(lines), data={"action": "list", "sessions": sessions})

    if args[0] == "delete":
        if len(args) < 2:
            return CommandResult(message="usage: /session delete <id>", status="error")
        try:
            session_id = store.resolve(args[1])
            store.delete(session_id)
        except SessionError as exc:
            return CommandResult(message=str(exc), status="error")
        return CommandResult(
            message=f"deleted session {session_id}",
            data={"action": "deleted", "session_id": session_id},
        )

    try:
        session_id = store.resolve(args[0])
    except SessionError as exc:
        return CommandResult(message=str(exc), status="error")
    return CommandResult(message=f"loading session {session_id}", data={"action": "load", "session_id": session_id})


def register_builtin_commands(registry: CommandRegistry) -> None:
    """注册全部内置命令。"""

    async def help_command(
        context: CommandContext,
        args: list[str],
    ) -> CommandResult:
        if args:
            return CommandResult(message="usage: /help", status="error")
        lines = []
        for command in registry.commands():
            usage = command.usage or f"/{command.name}"
            aliases = f" (别名: {', '.join('/' + alias for alias in command.aliases)})" if command.aliases else ""
            lines.append(f"{usage:<28} {command.description}{aliases}")
        return CommandResult(message="\n".join(lines), data={"action": "help"})

    registry.register(
        Command(
            name="help",
            description="显示所有命令",
            handler=help_command,
            aliases=("h",),
        )
    )
    registry.register(
        Command(
            name="clear",
            description="清空当前消息区（不删除会话历史）",
            handler=_clear,
        )
    )
    registry.register(
        Command(
            name="model",
            description="查看或切换当前模型",
            handler=_model,
            usage="/model [model_id]",
        )
    )
    registry.register(
        Command(
            name="status",
            description="查看会话与上下文统计",
            handler=_status,
        )
    )

    registry.register(
        Command(
            name="quit",
            description="退出对话",
            handler=_quit,
            aliases=("exit", "q"),
        )
    )
    registry.register(
        Command(
            name="compact",
            description="手动压缩当前会话上下文",
            handler=_compact,
            aliases=("c",),
        )
    )
    registry.register(
        Command(
            name="session",
            description="列出 / 载入 / 删除会话",
            handler=_session,
            aliases=("sessions",),
            usage="/session [id|delete <id>]",
        )
    )
