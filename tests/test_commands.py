"""coding_agent.commands — 命令系统测试。"""

import asyncio
from datetime import UTC, datetime

from agent_core.session.types import SessionError, SessionMeta
from coding_agent.commands import CommandContext, CommandRegistry, register_builtin_commands


def test_quit_command_exits() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(registry.execute("/quit", CommandContext(session=None)))

    assert result.should_exit is True
    assert result.message == "bye"


def test_quit_alias_exits() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(registry.execute("/q", CommandContext(session=None)))

    assert result.should_exit is True


def test_unknown_command_returns_error() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(registry.execute("/nosuch", CommandContext(session=None)))

    assert result.status == "error"
    assert "unknown command" in (result.message or "")


def test_non_command_returns_error() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(registry.execute("hello", CommandContext(session=None)))

    assert result.status == "error"


def test_complete_returns_canonical_name() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)

    assert registry.complete("/q") == ["quit"]
    assert registry.complete("/ex") == ["quit"]
    assert registry.complete("/c") == ["compact"]
    assert registry.complete("/s") == ["session"]
    assert registry.complete("/") == ["compact", "quit", "session"]


def test_complete_no_match_returns_empty() -> None:
    registry = CommandRegistry()
    register_builtin_commands(registry)

    assert registry.complete("/zzz") == []


def test_compact_command_calls_session_compact() -> None:
    class FakeSession:
        async def compact(self) -> str:
            return "已压缩"

    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(registry.execute("/compact", CommandContext(session=FakeSession())))

    assert result.status == "ok"
    assert result.message == "已压缩"


def test_compact_alias_works() -> None:
    class FakeSession:
        async def compact(self) -> str:
            return "已压缩"

    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(registry.execute("/c", CommandContext(session=FakeSession())))

    assert result.message == "已压缩"


class _FakeStore:
    def __init__(self, metas: list[SessionMeta]) -> None:
        self.metas = metas

    def list(self):
        return list(self.metas)

    def resolve(self, id_or_prefix: str) -> str:
        matches = [m.id for m in self.metas if m.id.startswith(id_or_prefix)]
        if len(matches) == 1:
            return matches[0]
        raise SessionError(f"session not found or ambiguous: {id_or_prefix}")

    def delete(self, session_id: str) -> None:
        self.metas = [m for m in self.metas if m.id != session_id]


def _meta(session_id: str) -> SessionMeta:
    now = datetime.now(UTC)
    return SessionMeta(id=session_id, cwd="/tmp", created_at=now, updated_at=now, max_turns=20, message_count=1)


def test_session_command_lists_sessions() -> None:
    store = _FakeStore([_meta("sess_abc"), _meta("sess_abd")])
    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(registry.execute("/session", CommandContext(session=None, session_store=store)))

    assert result.status == "ok"
    assert result.data["action"] == "list"
    assert [s["id"] for s in result.data["sessions"]] == ["sess_abc", "sess_abd"]


def test_session_command_loads_by_prefix() -> None:
    store = _FakeStore([_meta("sess_abc")])
    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(registry.execute("/session sess_ab", CommandContext(session=None, session_store=store)))

    assert result.data["action"] == "load"
    assert result.data["session_id"] == "sess_abc"


def test_session_command_delete() -> None:
    store = _FakeStore([_meta("sess_abc")])
    registry = CommandRegistry()
    register_builtin_commands(registry)

    result = asyncio.run(
        registry.execute("/session delete sess_abc", CommandContext(session=None, session_store=store))
    )

    assert result.data["action"] == "deleted"
    assert store.metas == []
