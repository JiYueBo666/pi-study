"""ai.openai_model — 流式适配器测试（假 SDK，不触网络）。"""

import asyncio
from datetime import datetime
from types import SimpleNamespace

from ai.openai_model import stream
from ai.types import (
    AssistantMessage,
    ModelConfig,
    ModelContext,
    StreamCompleted,
    StreamFailed,
    StreamStarted,
    TextContent,
    TextDelta,
    ToolCallContent,
    ToolCallDelta,
    UserMessage,
)

MODEL = ModelConfig(id="gpt-test")
TS = datetime(2026, 1, 1)


def _chunk(
    text: str | None = None,
    tool_calls: list | None = None,
    finish_reason: str | None = None,
    usage=None,
):
    return SimpleNamespace(
        usage=usage,
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=text, tool_calls=tool_calls or []), finish_reason=finish_reason
            )
        ],
    )


def _tc(index: int, id: str | None, name: str | None, arguments: str):
    return SimpleNamespace(index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments))


class FakeCompletions:
    def __init__(self, chunks: list) -> None:
        self.chunks = chunks
        self.calls = 0
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.calls += 1
        self.last_kwargs = kwargs

        async def gen():
            for c in self.chunks:
                yield c

        return gen()


class FakeClient:
    def __init__(self, chunks: list) -> None:
        self.chat = SimpleNamespace(completions=FakeCompletions(chunks))


def _ctx(text: str = "hi") -> ModelContext:
    return ModelContext(model=MODEL, messages=[UserMessage(content=text, timestamp=TS)])


async def _collect(client, context=None) -> list:
    model_context = context or _ctx()
    return [e async for e in stream(client, model_context.model, model_context)]


def test_text_stream_event_sequence() -> None:
    client = FakeClient(
        [
            _chunk(text="你"),
            _chunk(text="好"),
            _chunk(text="", finish_reason="stop"),
        ]
    )
    events = asyncio.run(_collect(client))
    assert [type(e).__name__ for e in events] == ["StreamStarted", "TextDelta", "TextDelta", "StreamCompleted"]
    deltas = [e for e in events if isinstance(e, TextDelta)]
    assert [d.delta for d in deltas] == ["你", "好"]
    comp = events[-1]
    assert isinstance(comp, StreamCompleted)
    assert comp.message.content == [TextContent(text="你好")]
    assert comp.message.stopReason == "stop"


def test_stream_preserves_final_usage() -> None:
    client = FakeClient(
        [
            _chunk(text="ok"),
            _chunk(
                finish_reason="stop",
                usage=SimpleNamespace(prompt_tokens=123, completion_tokens=7, total_tokens=130),
            ),
        ]
    )

    events = asyncio.run(_collect(client))

    comp = events[-1]
    assert isinstance(comp, StreamCompleted)
    assert comp.message.usage == {"prompt_tokens": 123, "completion_tokens": 7, "total_tokens": 130}
    assert client.chat.completions.calls == 1
    assert client.chat.completions.last_kwargs["stream_options"] == {"include_usage": True}


def test_stream_sends_configured_max_output_tokens() -> None:
    model = ModelConfig(id="gpt-test", context_window=128_000, max_output_tokens=4_000)
    client = FakeClient([_chunk(text="ok", finish_reason="stop")])

    asyncio.run(_collect(client, ModelContext(model=model, messages=[UserMessage(content="hi", timestamp=TS)])))

    assert client.chat.completions.last_kwargs["max_tokens"] == 4_000


def test_text_delta_carries_partial() -> None:
    client = FakeClient([_chunk(text="你"), _chunk(text="好"), _chunk(text="", finish_reason="stop")])
    events = asyncio.run(_collect(client))
    deltas = [(e.delta, e.partial) for e in events if isinstance(e, TextDelta)]
    assert deltas == [("你", "你"), ("好", "你好")]


def test_tool_call_stream_aggregates() -> None:
    client = FakeClient(
        [
            _chunk(tool_calls=[_tc(0, "call_1", "read", '{"path":')]),
            _chunk(tool_calls=[_tc(0, None, None, ' "a.py"}')]),
            _chunk(tool_calls=[], finish_reason="tool_calls"),
        ]
    )
    events = asyncio.run(_collect(client))
    assert len([e for e in events if isinstance(e, ToolCallDelta)]) == 2
    comp = [e for e in events if isinstance(e, StreamCompleted)][0]
    calls = [c for c in comp.message.content if isinstance(c, ToolCallContent)]
    assert calls[0].id == "call_1" and calls[0].name == "read"
    assert calls[0].arguments == {"path": "a.py"}
    assert comp.message.stopReason == "toolUse"


def test_no_tool_calls_does_not_crash() -> None:
    client = FakeClient([_chunk(text="ok", finish_reason="stop")])
    events = asyncio.run(_collect(client))
    comp = [e for e in events if isinstance(e, StreamCompleted)][0]
    assert comp.message.content == [TextContent(text="ok")]


def test_create_exception_becomes_stream_failed() -> None:
    class BoomCompletions:
        async def create(self, **kwargs):
            raise ConnectionError("boom")

    client = SimpleNamespace(chat=SimpleNamespace(completions=BoomCompletions()))
    events = asyncio.run(_collect(client))
    assert len(events) == 1
    assert isinstance(events[0], StreamFailed)
    assert "ConnectionError" in events[0].error


def test_stream_exception_becomes_stream_failed() -> None:
    async def raise_stream():
        yield _chunk(text="部分")
        raise ConnectionError("mid")

    async def create(**kwargs):
        return raise_stream()

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    events = asyncio.run(_collect(client))
    assert isinstance(events[0], StreamStarted)
    assert isinstance(events[-1], StreamFailed)


def test_message_params_serializes_tool_round_trip() -> None:
    """多轮工具调用格式：assistant 带 tool_calls，toolResult -> role=tool + tool_call_id。"""
    from ai.openai_model import _message_params
    from ai.types import ToolResult

    history = [
        UserMessage(content="读一下 app.py", timestamp=TS),
        AssistantMessage(
            content=[
                TextContent(text="我先读文件"),
                ToolCallContent(id="call_1", name="read", arguments={"path": "app.py"}),
            ],
            timestamp=TS,
            api="f",
            provider="f",
            model="f",
            usage={},
            stopReason="toolUse",
        ),
        ToolResult(
            toolCallId="call_1",
            toolName="read",
            content=[TextContent(text="def main(): pass")],
            details={},
            timestamp=TS,
        ),
    ]
    params = _message_params(ModelContext(model=MODEL, messages=history))
    assert params[0]["role"] == "user"
    # assistant：text + tool_calls 都保留
    assert params[1]["role"] == "assistant"
    assert params[1]["content"] == "我先读文件"
    assert params[1]["tool_calls"][0]["id"] == "call_1"
    assert params[1]["tool_calls"][0]["function"]["name"] == "read"
    assert params[1]["tool_calls"][0]["function"]["arguments"] == '{"path": "app.py"}'
    # toolResult：role=tool + 引用 id
    assert params[2]["role"] == "tool"
    assert params[2]["tool_call_id"] == "call_1"
    assert params[2]["content"] == "def main(): pass"
