"""JSONL 会话存储测试。"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_core.session.jsonl import JsonlSessionStore
from agent_core.session.types import SessionError, SessionMeta
from ai.types import (
    AssistantMessage,
    CompactionSummaryMessage,
    TextContent,
    ThinkingContent,
    ToolCallContent,
    ToolResult,
    UserMessage,
)


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


def test_session_store_roundtrips_all_persisted_message_types(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    messages = [
        UserMessage(content="检查项目", timestamp=timestamp),
        AssistantMessage(
            content=[
                ThinkingContent(thinking="先查看目录"),
                TextContent(text="我来检查。"),
                ToolCallContent(id="call-1", name="ls", arguments={"path": "."}),
            ],
            timestamp=timestamp,
            api="chat.completions",
            provider="fake",
            model="fake-model",
            usage={"input": 10, "output": 5},
            stopReason="toolUse",
        ),
        ToolResult(
            toolCallId="call-1",
            toolName="ls",
            content=[TextContent(text="README.md")],
            details={"path": "."},
            timestamp=timestamp,
            isError=False,
        ),
        CompactionSummaryMessage(
            summary="已检查项目目录",
            timestamp=timestamp,
            tokens_before=1000,
        ),
    ]

    store.save(_meta("sess_all"), messages)

    meta, loaded = store.load("sess_all")
    assert loaded == messages
    assert meta.message_count == len(messages)


def test_session_store_updates_message_count_on_repeated_save(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    first = [UserMessage(content="第一轮", timestamp=datetime.now(UTC))]
    second = [*first, UserMessage(content="第二轮", timestamp=datetime.now(UTC))]

    store.save(_meta("sess_repeat"), first)
    first_meta, _ = store.load("sess_repeat")
    store.save(_meta("sess_repeat"), second)
    second_meta, loaded = store.load("sess_repeat")

    assert first_meta.message_count == 1
    assert second_meta.message_count == 2
    assert loaded == second
    assert second_meta.updated_at >= first_meta.updated_at


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


def test_session_store_rejects_ambiguous_prefix(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    store.save(_meta("sess_ab1"), [])
    store.save(_meta("sess_ab2"), [])

    with pytest.raises(SessionError, match="ambiguous session prefix"):
        store.resolve("sess_ab")


def test_session_store_ignores_only_incomplete_final_line(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    store.save(_meta("sess_tail"), [UserMessage(content="保留", timestamp=datetime.now(UTC))])
    path = tmp_path / "sessions" / "sess_tail.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write('{"role":"user"')

    _, loaded = store.load("sess_tail")
    assert [message.content for message in loaded if isinstance(message, UserMessage)] == ["保留"]


def test_session_store_rejects_corrupt_middle_line(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    store.save(
        _meta("sess_corrupt"),
        [
            UserMessage(content="第一条", timestamp=datetime.now(UTC)),
            UserMessage(content="第二条", timestamp=datetime.now(UTC)),
        ],
    )
    path = tmp_path / "sessions" / "sess_corrupt.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines[1] = "{broken middle line}\n"
    path.write_text("".join(lines), encoding="utf-8")

    with pytest.raises(SessionError, match="corrupt session"):
        store.load("sess_corrupt")


def test_session_store_list_skips_invalid_files_and_sorts_by_updated_at(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    store.save(_meta("sess_old"), [])
    store.save(_meta("sess_new"), [])
    for session_id, updated_at in (
        ("sess_old", "2026-01-01T00:00:00+00:00"),
        ("sess_new", "2026-01-02T00:00:00+00:00"),
    ):
        path = tmp_path / "sessions" / f"{session_id}.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        meta = json.loads(lines[0])
        meta["updated_at"] = updated_at
        lines[0] = json.dumps(meta)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp_path / "sessions" / "broken.jsonl").write_text("not json\n", encoding="utf-8")

    assert [meta.id for meta in store.list()] == ["sess_new", "sess_old"]
