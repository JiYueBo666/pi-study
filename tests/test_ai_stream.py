"""ai.stream — AssistantMessageBuilder 聚合器测试。"""

from datetime import datetime

from ai.stream import AssistantMessageBuilder
from ai.types import TextContent, ToolCallContent

TS = datetime(2026, 1, 1)


def _builder() -> AssistantMessageBuilder:
    return AssistantMessageBuilder(model="m", provider="p", api="a", timestamp=TS)


def test_text_aggregates_into_single_text_block() -> None:
    b = _builder()
    b.add_text("你")
    b.add_text("好")
    m = b.build(stop_reason="stop", usage={})
    assert m.content == [TextContent(text="你好")]
    assert m.stopReason == "stop" and m.model == "m"


def test_empty_delta_ignored() -> None:
    b = _builder()
    b.add_text("")
    b.add_text("x")
    b.add_text("")
    m = b.build(stop_reason="stop", usage={})
    assert m.content == [TextContent(text="x")]


def test_empty_stream_builds_empty_content() -> None:
    b = _builder()
    m = b.build(stop_reason="stop", usage={})
    assert m.content == []


def test_partial_accumulates_in_order() -> None:
    b = _builder()
    b.add_text("你")
    assert b.get_parts == "你"
    b.add_text("好")
    assert b.get_parts == "你好"
    # 幂等：重复读不重复累积
    assert b.get_parts == "你好"


def test_partial_empty_stream_safe() -> None:
    b = _builder()
    assert b.get_parts == ""


def test_tool_call_arguments_parse_across_chunks() -> None:
    b = _builder()
    b.add_tool_call(0, "call_1", "read", '{"path":')
    b.add_tool_call(0, None, None, ' "a.py"}')
    m = b.build(stop_reason="toolUse", usage={})
    calls = [c for c in m.content if isinstance(c, ToolCallContent)]
    assert len(calls) == 1
    assert calls[0].id == "call_1"
    assert calls[0].name == "read"
    assert calls[0].arguments == {"path": "a.py"}


def test_multiple_tool_calls_in_order() -> None:
    b = _builder()
    b.add_tool_call(0, "c0", "read", '{"path":"a.py"}')
    b.add_tool_call(1, "c1", "grep", '{"pattern":"TODO"}')
    m = b.build(stop_reason="toolUse", usage={})
    calls = [c for c in m.content if isinstance(c, ToolCallContent)]
    assert len(calls) == 2
    assert calls[0].name == "read" and calls[1].name == "grep"


def test_text_and_tool_call_coexist() -> None:
    b = _builder()
    b.add_text("看下")
    b.add_tool_call(0, "c1", "read", '{"path":"a.py"}')
    m = b.build(stop_reason="toolUse", usage={})
    assert m.content[0] == TextContent(text="看下")
    assert isinstance(m.content[1], ToolCallContent)


def test_malformed_arguments_become_empty_dict() -> None:
    """阶段 2 宽容策略：畸形 JSON -> 空 dict，不崩溃。"""
    b = _builder()
    b.add_tool_call(0, "c1", "bash", "{broken")
    m = b.build(stop_reason="toolUse", usage={})
    calls = [c for c in m.content if isinstance(c, ToolCallContent)]
    assert calls[0].arguments == {}


def test_thinking_accumulates_before_text_block() -> None:
    from ai.types import ThinkingContent

    b = _builder()
    b.add_thinking("让我想想")
    b.add_thinking("……")
    b.add_text("答案")
    m = b.build(stop_reason="stop", usage={})
    assert isinstance(m.content[0], ThinkingContent)
    assert m.content[0].thinking == "让我想想……"
    assert m.content[1] == TextContent(text="答案")
    assert b.get_thinking == "让我想想……"


def test_thinking_empty_stream_safe() -> None:
    b = _builder()
    assert b.get_thinking == ""
