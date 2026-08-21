"""agent_core.run_loop — 事件序列、多轮工具循环、max_turns、历史累积。"""

import asyncio
from datetime import datetime

import pytest

from agent_core.loop import _execute_tool_with_progress, run_loop
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
    is_safe = True
    parameters = {}

    async def execute(self, call, cancel, on_progress=None) -> ToolExecutionResult:
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


def test_incomplete_provider_stream_returns_internal_error() -> None:
    class IncompleteProvider:
        async def stream(self, context):
            return
            yield  # make this an async generator

    result, events = asyncio.run(_run(IncompleteProvider()))

    assert result == "模型调用未返回完整消息"
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


def test_before_tool_call_hook_can_override_execution() -> None:
    class MustNotExecuteTool(AgentTool):
        name = "blocked"
        description = ""

        async def execute(self, call, cancel, on_progress=None) -> ToolExecutionResult:
            raise AssertionError("工具被覆盖后不应执行")

    provider = FakeProvider(
        [
            _msg([_tool_call("blocked")], "toolUse"),
            _msg([TextContent(text="继续")]),
        ]
    )
    emit = NoopEmit()

    async def before_tool_call(tool, call) -> ToolExecutionResult:
        return ToolExecutionResult(content="blocked by business", is_error=True)

    async def run() -> str:
        return await run_loop(
            provider=provider,
            model=MODEL,
            system_prompt=None,
            user_prompt="hi",
            emit=emit,
            tools=[MustNotExecuteTool()],
            history=(),
            before_tool_call_hook=before_tool_call,
        )

    assert asyncio.run(run()) == "继续"
    assert "ToolStarted" not in emit.events
    assert "ToolCompleted" in emit.events


class ProgressTool(AgentTool):
    name = "progress"
    description = ""
    is_safe = True
    parameters = {}

    async def execute(self, call, cancel, on_progress=None) -> ToolExecutionResult:
        if on_progress:
            on_progress("第一行")
            on_progress("第二行")
        return ToolExecutionResult(content="done")


def test_tool_progress_events_emitted_in_order() -> None:
    provider = FakeProvider(
        [
            _msg([_tool_call("progress")], "toolUse"),
            _msg([TextContent(text="完成")]),
        ]
    )
    emit = NoopEmit()

    async def run() -> None:
        await run_loop(
            provider=provider,
            model=MODEL,
            system_prompt=None,
            user_prompt="hi",
            emit=emit,
            tools=[ProgressTool()],
            max_turns=20,
            history=(),
        )

    asyncio.run(run())
    assert emit.events.count("ToolUpdated") == 2
    # 进度事件在 ToolCompleted 之前按序发出
    assert emit.events.index("ToolUpdated") < emit.events.index("ToolCompleted")


def test_tool_progress_events_gathered_when_tool_raises() -> None:
    class ExplodingTool(AgentTool):
        name = "boom"
        description = ""
        is_safe = True
        parameters = {}

        async def execute(self, call, cancel, on_progress=None) -> ToolExecutionResult:
            if on_progress:
                on_progress("before raise")
            raise RuntimeError("boom")

    events: list[object] = []

    async def emit(event) -> None:
        events.append(event)

    async def run() -> None:
        with pytest.raises(RuntimeError, match="boom"):
            await _execute_tool_with_progress(
                ExplodingTool(),
                _tool_call("boom"),
                asyncio.Event(),
                emit,
            )

    asyncio.run(run())
    assert any(type(e).__name__ == "ToolUpdated" for e in events)


def test_tool_progress_events_gathered_when_tool_cancelled() -> None:
    class CancelledTool(AgentTool):
        name = "cancel"
        description = ""
        is_safe = True
        parameters = {}

        async def execute(self, call, cancel, on_progress=None) -> ToolExecutionResult:
            if on_progress:
                on_progress("before cancel")
            raise asyncio.CancelledError()

    events: list[object] = []

    async def emit(event) -> None:
        events.append(event)

    async def run() -> None:
        with pytest.raises(asyncio.CancelledError):
            await _execute_tool_with_progress(
                CancelledTool(),
                _tool_call("cancel"),
                asyncio.Event(),
                emit,
            )

    asyncio.run(run())
    assert any(type(e).__name__ == "ToolUpdated" for e in events)
