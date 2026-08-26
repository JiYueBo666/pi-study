"""coding_agent.session — CodingSession 端到端（假 Provider 驱动全工具链）。"""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from agent_core.session.jsonl import JsonlSessionStore
from ai.types import (
    AssistantMessage,
    ModelConfig,
    StreamCompleted,
    TextContent,
    ToolCallContent,
    ToolResult,
)
from coding_agent.event import ToolApprovalCompleted, ToolApprovalRequested
from coding_agent.session import CodingSession
from coding_agent.tools_pacakge.tool_config import ApprovalMode

MODEL = ModelConfig(id="fake", context_window=100_000, max_output_tokens=1_000)
TS = datetime(2026, 1, 1)


class ScriptedProvider:
    def __init__(self, responses: list[AssistantMessage]) -> None:
        self.responses = list(responses)
        self.sent: list = []
        self.models: list[str] = []

    async def stream(self, context):
        self.sent.append([m.role for m in context.messages])
        self.models.append(context.model.id)
        yield StreamCompleted(message=self.responses.pop(0))


def _tool_call(name: str = "read", **args) -> ToolCallContent:
    return ToolCallContent(id="c1", name=name, arguments=args)


def _msg(content: list, stop_reason: str = "stop", usage: dict | None = None) -> AssistantMessage:
    return AssistantMessage(
        content=content,
        timestamp=TS,
        api="fake",
        provider="fake",
        model="fake",
        usage=usage or {"prompt_tokens": 42},
        stopReason=stop_reason,
    )


def test_session_reads_and_reports(tmp_path: Path) -> None:
    """场景 B 自动化：read 文件 -> 模型基于结果回答。"""
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n")
    provider = ScriptedProvider(
        [
            _msg([_tool_call(path="app.py")], "toolUse"),
            _msg([TextContent(text="add 函数在 app.py 第 1 行")]),
        ]
    )
    session = CodingSession(provider=provider, model=MODEL, root=tmp_path)
    result = asyncio.run(session.prompt("add 函数在哪"))
    assert result == "add 函数在 app.py 第 1 行"
    # 工具结果进入第二次模型调用的上下文
    assert provider.sent[1] == ["user", "assistant", "toolResult"]


def test_session_max_turns_wiring(tmp_path: Path) -> None:
    class AlwaysTool:
        async def stream(self, context):
            yield StreamCompleted(message=_msg([_tool_call(path="a.py")], "toolUse"))

    session = CodingSession(provider=AlwaysTool(), model=MODEL, root=tmp_path, max_turns=2)
    result = asyncio.run(session.prompt("hi"))
    assert result == "达到max turn轮数: 2 轮"


def test_session_events_observable(tmp_path: Path) -> None:
    provider = ScriptedProvider([_msg([TextContent(text="回答")])])
    session = CodingSession(provider=provider, model=MODEL, root=tmp_path)
    events: list = []

    async def sink(e):
        events.append(type(e).__name__)

    session.agent.subscribe(sink)
    asyncio.run(session.prompt("hi"))
    assert "AgentStarted" in events and "AgentEnded" in events


def test_session_switches_model_for_next_provider_call(tmp_path: Path) -> None:
    provider = ScriptedProvider([_msg([TextContent(text="回答")])])
    session = CodingSession(provider=provider, model=MODEL, root=tmp_path)

    selected = session.set_model("new-model")
    result = asyncio.run(session.prompt("hi"))

    assert selected.id == "new-model"
    assert selected.context_window == 100_000
    assert selected.max_output_tokens == 1_000
    assert session.model.id == "new-model"
    assert provider.models == ["new-model"]
    assert result == "回答"


def test_session_status_reports_context_without_mutating_history(tmp_path: Path) -> None:
    provider = ScriptedProvider([_msg([TextContent(text="回答")])])
    session = CodingSession(provider=provider, model=MODEL, root=tmp_path)
    asyncio.run(session.prompt("hello"))

    before = session.messages
    status = session.status()

    assert status["model"] == "fake"
    assert status["message_count"] == 2
    assert status["role_counts"] == {"user": 1, "assistant": 1}
    assert status["context_tokens"] == 42
    assert status["compaction_threshold"] == 99_000
    assert session.messages == before


def test_saved_history_can_be_restored_into_next_session_context(tmp_path: Path) -> None:
    store = JsonlSessionStore(tmp_path / "sessions")
    first_provider = ScriptedProvider([_msg([TextContent(text="第一轮回答")])])
    first = CodingSession(provider=first_provider, model=MODEL, root=tmp_path, session_store=store)
    asyncio.run(first.prompt("第一轮问题"))
    first.save()

    session_id = first.session_id
    assert session_id is not None
    _, history = store.load(session_id)

    second_provider = ScriptedProvider([_msg([TextContent(text="恢复后回答")])])
    second = CodingSession(
        provider=second_provider,
        model=MODEL,
        root=tmp_path,
        session_id=session_id,
        history=history,
        session_store=store,
    )
    result = asyncio.run(second.prompt("恢复后问题"))

    assert result == "恢复后回答"
    assert second_provider.sent[0] == ["user", "assistant", "user"]


def test_session_approval_waits_and_resolves_from_business_layer(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            _msg(
                [
                    _tool_call(
                        "write",
                        path="app.py",
                        content="print('hello')",
                    )
                ],
                "toolUse",
            ),
            _msg([TextContent(text="已完成")]),
        ]
    )
    session = CodingSession(provider=provider, model=MODEL, root=tmp_path)
    approval_events: list[ToolApprovalRequested | ToolApprovalCompleted] = []

    async def listener(event) -> None:
        if isinstance(event, ToolApprovalRequested):
            approval_events.append(event)
            assert session.resolve_tool_approval(event.request.request_id, False)
        elif isinstance(event, ToolApprovalCompleted):
            approval_events.append(event)

    session.subscribe(listener)

    result = asyncio.run(session.prompt("写入 app.py"))

    assert result == "已完成"
    assert [type(event).__name__ for event in approval_events] == [
        "ToolApprovalRequested",
        "ToolApprovalCompleted",
    ]
    assert session._pending_approvals == {}
    result_message = session.messages[2]
    assert isinstance(result_message, ToolResult)
    assert "用户拒绝了本次工具调用" in result_message.content[0].text


def test_auto_accept_skips_approval_event(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [
            _msg(
                [_tool_call("write", path="app.py", content="print('hello')")],
                "toolUse",
            ),
            _msg([TextContent(text="已完成")]),
        ]
    )
    session = CodingSession(provider=provider, model=MODEL, root=tmp_path)
    session.approval_mode = ApprovalMode.AutoAccept
    events: list[str] = []

    async def listener(event) -> None:
        events.append(type(event).__name__)

    session.subscribe(listener)

    result = asyncio.run(session.prompt("写入 app.py"))

    assert result == "已完成"
    assert "ToolApprovalRequested" not in events


def test_cancel_cleans_up_pending_approval(tmp_path: Path) -> None:
    session = CodingSession(provider=None, model=MODEL, root=tmp_path)
    write_tool = next(tool for tool in session.tools if tool.name == "write")

    async def run() -> None:
        task = asyncio.create_task(
            session.request_approval(
                write_tool,
                _tool_call("write", path="app.py", content="hello"),
            )
        )
        await asyncio.sleep(0)
        assert session._pending_approvals

        session.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert session._pending_approvals == {}

    asyncio.run(run())
