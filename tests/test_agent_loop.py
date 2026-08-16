"""agent_core.run_loop — 事件序列、多轮工具循环、max_turns、历史累积。"""

import asyncio
from datetime import datetime

from agent_core.loop import run_loop
from agent_core.types import AgentTool, ToolExecutionResult
from ai.types import (
    AssistantMessage,
    ModelConfig,
    StreamCompleted,
    StreamFailed,
    TextContent,
    ToolCallContent,
)

MODEL = ModelConfig(id="fake")
TS = datetime(2026, 1, 1)


def _msg(content: list, stop_reason: str = "stop") -> AssistantMessage:
    return AssistantMessage(
        content=content, timestamp=TS, api="fake", provider="fake", model="fake", usage={}, stopReason=stop_reason
    )


def _tool_call(name: str = "read", **args) -> ToolCallContent:
    return ToolCallContent(id="c1", name=name, arguments=args)


class ReadTool(AgentTool):
    name = "read"
    description = ""
    parameters = {}

    async def execute(self, call, cancel) -> ToolExecutionResult:
        return ToolExecutionResult(content="文件内容")


class NoopEmit:
    def __init__(self) -> None:
        self.events: list = []

    async def __call__(self, event) -> None:
        self.events.append(type(event).__name__)


async def _run(provider, *, tools=(), max_turns=20, user_prompt="hi", history=()):
    emit = NoopEmit()
    result = await run_loop(
        provider=provider,
        model=MODEL,
        system_prompt=None,
        user_prompt=user_prompt,
        emit=emit,
        tools=tools,
        max_turns=max_turns,
        history=history,
    )
    return result, emit.events


class FakeProvider:
    def __init__(self, responses: list[AssistantMessage]) -> None:
        self.responses = list(responses)
        self.sent_contexts: list = []

    async def stream(self, context):
        self.sent_contexts.append([m.role for m in context.messages])
        yield StreamCompleted(message=self.responses.pop(0))


def test_event_sequence_single_turn() -> None:
    provider = FakeProvider([_msg([TextContent(text="你好")])])
    result, events = asyncio.run(_run(provider))
    assert result == "你好"
    assert events == [
        "AgentStarted",
        "MessageStarted",
        "MessageCompleted",
        "TurnStarted",
        "MessageStarted",
        "MessageCompleted",
        "TurnEnded",
        "AgentEnded",
    ]


def test_tool_loop_two_turns() -> None:
    provider = FakeProvider(
        [
            _msg([TextContent(text="让我看看"), _tool_call()], "toolUse"),
            _msg([TextContent(text="找到了")]),
        ]
    )
    result, events = asyncio.run(_run(provider, tools=[ReadTool()]))
    assert result == "找到了"
    # 两轮：第 1 轮工具调用，第 2 轮完成
    assert "ToolStarted" in events and "ToolCompleted" in events
    assert events.count("TurnStarted") == 2


def test_tool_result_in_context_next_turn() -> None:
    provider = FakeProvider(
        [
            _msg([_tool_call()], "toolUse"),
            _msg([TextContent(text="完成")]),
        ]
    )
    asyncio.run(_run(provider, tools=[ReadTool()]))
    # 第 2 轮收到的历史：user + assistant(工具请求) + toolResult
    assert provider.sent_contexts[1] == ["user", "assistant", "toolResult"]


def test_max_turns_limits_loop() -> None:
    class AlwaysToolProvider:
        async def stream(self, context):
            yield StreamCompleted(message=_msg([_tool_call()], "toolUse"))

    result, events = asyncio.run(_run(AlwaysToolProvider(), tools=[ReadTool()], max_turns=2))
    assert result == "达到max turn轮数: 2 轮"
    assert events.count("TurnStarted") == 2
    assert "AgentEnded" in events


def test_model_failed_path() -> None:
    class FailProvider:
        async def stream(self, context):
            yield StreamFailed(error="ConnectionError: boom")

    result, events = asyncio.run(_run(FailProvider()))
    assert "模型调用失败" in result
    assert "AgentEnded" in events


def test_history_accumulates_across_user_inputs() -> None:
    """第二次 run 时带上第一次的完整轨迹（user + assistant）。"""
    from ai.types import UserMessage

    provider = FakeProvider([_msg([TextContent(text="回答1")]), _msg([TextContent(text="回答2")])])
    asyncio.run(_run(provider, user_prompt="问题1"))
    # 第二次 run：history = 第一次的完整轨迹（user 问题1 + assistant 回答1）
    history = [UserMessage(content="问题1", timestamp=TS), _msg([TextContent(text="回答1")])]
    asyncio.run(_run(provider, user_prompt="问题2", history=history))
    # 第二次调用模型时历史 = user(问题1) + assistant(回答1) + user(问题2)
    assert provider.sent_contexts[1] == ["user", "assistant", "user"]


def test_unknown_tool_returns_error_result() -> None:
    provider = FakeProvider(
        [
            _msg([_tool_call("nosuch")], "toolUse"),
            _msg([TextContent(text="继续")]),
        ]
    )
    result, _ = asyncio.run(_run(provider, tools=[]))
    assert result == "继续"
