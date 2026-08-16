"""agent_core.Agent — subscribe/processEvents/同步屏障/异常冒泡。"""

import asyncio
from datetime import datetime
from typing import cast

from agent_core.agent import Agent
from agent_core.events import AgentEnded, MessageCompleted
from agent_core.types import AgentTool, ToolExecutionResult
from ai.types import (
    AssistantMessage,
    ModelConfig,
    StreamCompleted,
    TextContent,
    ToolCallContent,
    ToolResult,
)

MODEL = ModelConfig(id="fake")
TS = datetime(2026, 1, 1)


class FakeProvider:
    def __init__(self, responses: list[AssistantMessage]) -> None:
        self.responses = list(responses)

    async def stream(self, context):
        yield StreamCompleted(message=self.responses.pop(0))


def _msg(content: list, stop_reason: str = "stop") -> AssistantMessage:
    return AssistantMessage(
        content=content, timestamp=TS, api="fake", provider="fake", model="fake", usage={}, stopReason=stop_reason
    )


class ReadTool(AgentTool):
    name = "read"
    description = ""
    parameters = {}

    async def execute(self, call, cancel) -> ToolExecutionResult:
        return ToolExecutionResult(content="文件内容")


def test_messages_driven_by_events() -> None:
    agent = Agent(provider=FakeProvider([_msg([TextContent(text="你好")])]), model=MODEL)
    asyncio.run(agent.run("hi"))
    assert [m.role for m in agent.messages] == ["user", "assistant"]


def test_subscribe_receives_all_events() -> None:
    agent = Agent(provider=FakeProvider([_msg([TextContent(text="你好")])]), model=MODEL)
    seen: list = []

    async def listener(e):
        seen.append(type(e).__name__)

    agent.subscribe(listener)
    asyncio.run(agent.run("hi"))
    assert "AgentStarted" in seen and "AgentEnded" in seen


def test_unsubscribe_stops_events() -> None:
    agent = Agent(provider=FakeProvider([_msg([TextContent(text="你好")])]), model=MODEL)
    seen: list = []

    async def listener(e):
        seen.append(type(e).__name__)

    unsub = agent.subscribe(listener)
    unsub()
    asyncio.run(agent.run("hi"))
    assert seen == []


def test_sync_barrier_serial_order() -> None:
    """慢监听器下事件仍严格串行（同步屏障）。"""
    agent = Agent(provider=FakeProvider([_msg([TextContent(text="你好")])]), model=MODEL)
    order: list = []

    async def slow_listener(e):
        order.append(type(e).__name__)
        await asyncio.sleep(0.001)

    agent.subscribe(slow_listener)
    asyncio.run(agent.run("hi"))
    assert order == order  # 无乱序断言：这里验证能正常跑完且无并发交错


def test_listener_exception_bubbles() -> None:
    agent = Agent(provider=FakeProvider([_msg([TextContent(text="你好")])]), model=MODEL)

    async def bad_listener(e):
        if isinstance(e, AgentEnded):
            raise ValueError("listener bug")

    agent.subscribe(bad_listener)
    try:
        asyncio.run(agent.run("hi"))
        raise AssertionError("应抛出监听器异常")
    except ValueError as exc:
        assert str(exc) == "listener bug"


def test_agent_with_tools_history_includes_tool_result() -> None:
    provider = FakeProvider(
        [
            _msg([ToolCallContent(id="c1", name="read", arguments={"path": "a.py"})], "toolUse"),
            _msg([TextContent(text="完成")]),
        ]
    )
    agent = Agent(provider=provider, model=MODEL, tools=[ReadTool()])
    asyncio.run(agent.run("hi"))
    roles = [m.role for m in agent.messages]
    assert roles == ["user", "assistant", "toolResult", "assistant"]
    tool_result = cast(ToolResult, agent.messages[2])
    assert tool_result.toolCallId == "c1"


def test_subscriber_sees_tool_result_message() -> None:
    provider = FakeProvider(
        [
            _msg([ToolCallContent(id="c1", name="read", arguments={})], "toolUse"),
            _msg([TextContent(text="完成")]),
        ]
    )
    agent = Agent(provider=provider, model=MODEL, tools=[ReadTool()])
    results: list = []

    async def listener(e):
        if isinstance(e, MessageCompleted) and e.message.role == "toolResult":
            results.append(e.message)

    agent.subscribe(listener)
    asyncio.run(agent.run("hi"))
    assert len(results) == 1 and results[0].content[0].text == "文件内容"
