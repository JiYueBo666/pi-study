"""coding_agent.render — 终端渲染器测试。"""

from datetime import datetime

from agent_core.events import AgentEnded, ToolCompleted, ToolStarted
from ai.types import TextContent, ToolCallContent, ToolResult
from coding_agent.render import TerminalRenderer, _arg_summary, _result_summary, _result_text


def test_arg_summary_long_text_truncated() -> None:
    summary = _arg_summary({"content": "x" * 100})
    assert "60" in summary or "…" in summary
    assert "100 字符" in summary


def test_arg_summary_multiline_shows_line_count() -> None:
    summary = _arg_summary({"content": "a\nb\nc"})
    assert "3 行" in summary


def test_result_text_extracts_from_content_blocks() -> None:
    result = ToolResult(
        toolCallId="c1",
        toolName="read",
        content=[TextContent(text="line1\nline2")],
        details={},
        timestamp=datetime(2026, 1, 1),
    )
    assert _result_text(result) == "line1\nline2"


def test_result_summary_read_lines() -> None:
    result = ToolResult(
        toolCallId="c1",
        toolName="read",
        content=[TextContent(text="a\nb\nc")],
        details={"truncated": False},
        timestamp=datetime(2026, 1, 1),
    )
    assert _result_summary("read", result, _result_text(result)) == "3 行"


def test_result_summary_bash_exit_code() -> None:
    result = ToolResult(
        toolCallId="c1",
        toolName="bash",
        content=[TextContent(text="output")],
        details={"exit_code": 3, "timed_out": False},
        timestamp=datetime(2026, 1, 1),
    )
    assert _result_summary("bash", result, _result_text(result)) == "exit 3"


def test_renderer_tool_started_and_completed(capsys) -> None:
    renderer = TerminalRenderer(color=False)
    call = ToolCallContent(id="c1", name="ls", arguments={})
    result = ToolResult(
        toolCallId="c1",
        toolName="ls",
        content=[TextContent(text="a.py\nb.py")],
        details={},
        timestamp=datetime(2026, 1, 1),
    )
    renderer(ToolStarted(call))
    renderer(ToolCompleted(call, result))
    out = capsys.readouterr().out
    assert "▶ ls()" in out
    assert "✓ 2 条" in out


def test_renderer_ended_label(capsys) -> None:
    renderer = TerminalRenderer(color=False)
    renderer(AgentEnded(status="completed"))
    out = capsys.readouterr().out
    assert "✓ completed" in out


def test_renderer_thinking_then_text(capsys) -> None:
    from agent_core.events import MessageDelta, ThinkingDeltaEvent

    renderer = TerminalRenderer(color=False)
    renderer(ThinkingDeltaEvent(delta="思考中", partial="思考中"))
    renderer(ThinkingDeltaEvent(delta="……", partial="思考中……"))
    renderer(MessageDelta(delta="回答", partial="回答"))
    out = capsys.readouterr().out
    assert "💭" in out
    assert "思考中" in out
    assert "回答" in out
    # 思考与正文之间换行
    assert "\n回答" in out
