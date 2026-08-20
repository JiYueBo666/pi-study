"""JSONL 会话存储测试。"""

from datetime import UTC, datetime

import pytest

from agent_core.session.jsonl import JsonlSessionStore
from agent_core.session.types import SessionError, SessionMeta
from ai.types import UserMessage


def _meta(session_id: str) -> SessionMeta:
    now = datetime.now(UTC)
    return SessionMeta(
        id=session_id,
        cwd="/tmp/workspace",
        created_at=now,
        updated_at=now,
        max_turns=20,
        message_count=0,
    )


def test_session_store_roundtrip_list_and_delete(tmp_path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    messages = [UserMessage(content="hello", timestamp=datetime.now(UTC))]

    store.save(_meta("sess_abc"), messages)

    meta, loaded = store.load("sess_abc")
    assert meta.id == "sess_abc"
    assert meta.message_count == 1
    assert loaded == messages
    assert [item.id for item in store.list()] == ["sess_abc"]

    store.delete("sess_abc")
    with pytest.raises(SessionError, match="session not found"):
        store.load("sess_abc")


@pytest.mark.parametrize("session_id", ["../../outside", "/tmp/outside", "sess/foo", ""])
def test_session_store_rejects_path_like_ids(tmp_path, session_id: str) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")

    with pytest.raises(SessionError, match="invalid session id"):
        store.resolve(session_id)


def test_session_store_resolves_unique_prefix(tmp_path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    store.save(_meta("sess_abc"), [])

    assert store.resolve("sess_ab") == "sess_abc"
    assert store.resolve("sess") == "sess_abc"
