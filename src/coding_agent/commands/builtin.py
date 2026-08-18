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
        )
    )
