"""agent_core.compaction — 上下文压缩测试。"""

import asyncio
from datetime import UTC, datetime

from agent_core.compaction import (
    CompactionSettings,
    CompactionSummaryMessage,
    compact_messages,
    estimate_tokens,
    find_cut_index,
    should_compact,
)
from ai.types import AssistantMessage, ModelConfig, StreamCompleted, TextContent, UserMessage

TS = datetime.now(UTC)
MODEL = ModelConfig(id="fake")


def _user(content: str = "hello") -> UserMessage:
    return UserMessage(content=content, timestamp=TS)


def _assistant(text: str = "hi") -> AssistantMessage:
    return AssistantMessage(
        content=[TextContent(text=text)],
        timestamp=TS,
        api="fake",
        provider="fake",
        model="fake",
        usage={},
        stopReason="stop",
    )


class FakeProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def stream(self, context):
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")
        yield StreamCompleted(message=_assistant(text="summary"))


def test_estimate_tokens_user() -> None:
    assert estimate_tokens(_user("x" * 40)) == 10


def test_should_compact_threshold() -> None:
    settings = CompactionSettings(
        enabled=True,
        reserve_tokens=10,
        keep_recent_tokens=50,
        max_context_tokens=100,
    )
    small = [_user("x" * 20) for _ in range(5)]
    big = [_user("x" * 40) for _ in range(20)]

    assert not should_compact(small, settings)
    assert should_compact(big, settings)


def test_find_cut_index_respects_turn_boundary() -> None:
    messages = [
        _user("q1"),
        _assistant("a1"),
        _user("q2"),
        _assistant("a2"),
        _user("q3"),
        _assistant("a3"),
    ]
    # keep_recent_tokens 很小，只能保留最后一个轮次
    assert find_cut_index(messages, keep_recent_tokens=1) == 4


def test_compact_messages_auto_not_trigger() -> None:
    settings = CompactionSettings(
        enabled=True,
        reserve_tokens=10,
        keep_recent_tokens=50,
        max_context_tokens=100,
    )
    messages = [_user("hello") for _ in range(3)]
    provider = FakeProvider()

    result = asyncio.run(compact_messages(messages, provider, MODEL, settings, force=False))

    assert provider.calls == 0
    assert result == messages


def test_compact_messages_auto_trigger() -> None:
    settings = CompactionSettings(
        enabled=True,
        reserve_tokens=10,
        keep_recent_tokens=50,
        max_context_tokens=100,
    )
    messages = [_user("x" * 40) for _ in range(20)]
    provider = FakeProvider()

    result = asyncio.run(compact_messages(messages, provider, MODEL, settings, force=False))

    assert provider.calls == 1
    assert isinstance(result[0], CompactionSummaryMessage)
    assert len(result) > 1


def test_compact_messages_force_keeps_last_turn() -> None:
    settings = CompactionSettings(
        enabled=True,
        reserve_tokens=10,
        keep_recent_tokens=50,
        max_context_tokens=100,
    )
    messages = [
        _user("q1"),
        _assistant("a1"),
        _user("q2"),
        _assistant("a2"),
    ]
    provider = FakeProvider()

    result = asyncio.run(compact_messages(messages, provider, MODEL, settings, force=True))

    assert provider.calls == 1
    assert isinstance(result[0], CompactionSummaryMessage)
    assert result[1:] == messages[2:]


def test_compact_messages_summary_failure_safe() -> None:
    settings = CompactionSettings(
        enabled=True,
        reserve_tokens=10,
        keep_recent_tokens=50,
        max_context_tokens=100,
    )
    messages = [
        _user("q1"),
        _assistant("a1"),
        _user("q2"),
        _assistant("a2"),
    ]
    provider = FakeProvider(fail=True)

    result = asyncio.run(compact_messages(messages, provider, MODEL, settings, force=True))

    assert result == messages
