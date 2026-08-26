"""agent_core.compaction — 上下文压缩测试。"""

import asyncio
from datetime import UTC, datetime

from agent_core.compaction import (
    CompactionSettings,
    CompactionSummaryMessage,
    compact_messages,
    find_cut_index,
    input_token_limit,
    latest_prompt_tokens,
    should_compact,
)
from ai.types import AssistantMessage, ModelConfig, StreamCompleted, TextContent, UserMessage

TS = datetime.now(UTC)
MODEL = ModelConfig(id="fake", context_window=100, max_output_tokens=10)


def _user(content: str = "hello") -> UserMessage:
    return UserMessage(content=content, timestamp=TS)


def _assistant(text: str = "hi", usage: dict | None = None) -> AssistantMessage:
    return AssistantMessage(
        content=[TextContent(text=text)],
        timestamp=TS,
        api="fake",
        provider="fake",
        model="fake",
        usage=usage or {},
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


def test_should_compact_uses_real_prompt_usage_and_model_window() -> None:
    settings = CompactionSettings(reserve_tokens=10)
    below_limit = [_user(), _assistant(usage={"prompt_tokens": 90})]
    above_limit = [_user(), _assistant(usage={"prompt_tokens": 91})]

    assert input_token_limit(MODEL, settings) == 90
    assert latest_prompt_tokens(above_limit) == 91
    assert not should_compact(below_limit, MODEL, settings)
    assert should_compact(above_limit, MODEL, settings)


def test_should_not_compact_when_usage_or_window_is_unknown() -> None:
    settings = CompactionSettings(reserve_tokens=10)
    no_usage = [_user(), _assistant()]
    no_window = [_user(), _assistant(usage={"prompt_tokens": 10_000})]

    assert not should_compact(no_usage, MODEL, settings)
    assert not should_compact(no_window, ModelConfig(id="unknown"), settings)


def test_find_cut_index_respects_turn_boundary() -> None:
    messages = [
        _user("q1"),
        _assistant("a1"),
        _user("q2"),
        _assistant("a2"),
        _user("q3"),
        _assistant("a3"),
    ]
    # 保留最近一个轮次，切点不会拆散工具调用及其结果。
    assert find_cut_index(messages, keep_recent_turns=1) == 4


def test_compact_messages_auto_not_trigger() -> None:
    settings = CompactionSettings(enabled=True, reserve_tokens=10)
    messages = [_user("hello") for _ in range(3)]
    provider = FakeProvider()

    result = asyncio.run(compact_messages(messages, provider, MODEL, settings, force=False))

    assert provider.calls == 0
    assert result == messages


def test_compact_messages_auto_trigger() -> None:
    settings = CompactionSettings(enabled=True, reserve_tokens=10)
    messages = [
        _user("first"),
        _assistant("first answer", usage={"prompt_tokens": 91}),
        _user("second"),
        _assistant("second answer", usage={"prompt_tokens": 91}),
    ]
    provider = FakeProvider()

    result = asyncio.run(compact_messages(messages, provider, MODEL, settings, force=False))

    assert provider.calls == 1
    assert isinstance(result[0], CompactionSummaryMessage)
    assert result[0].tokens_before == 91
    assert result[1:] == messages[2:]


def test_compact_messages_force_keeps_last_turn() -> None:
    settings = CompactionSettings(enabled=True, reserve_tokens=10)
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
    settings = CompactionSettings(enabled=True, reserve_tokens=10)
    messages = [
        _user("q1"),
        _assistant("a1"),
        _user("q2"),
        _assistant("a2"),
    ]
    provider = FakeProvider(fail=True)

    result = asyncio.run(compact_messages(messages, provider, MODEL, settings, force=True))

    assert result == messages
