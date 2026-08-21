"""TUI 状态行为测试。"""

from types import SimpleNamespace

from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.widgets import Collapsible, Static

from tui.widgets import ToolResultView, _output_lexer
from tui_app.screens import SessionPickerScreen


class _HostApp(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


class _ToolResultHost(App):
    def __init__(self, view: ToolResultView) -> None:
        super().__init__()
        self.view = view

    def compose(self) -> ComposeResult:
        yield self.view


def _session() -> dict:
    return {
        "id": "sess_abc",
        "cwd": "/tmp/workspace",
        "updated_at": "2026-01-01T00:00:00+00:00",
        "message_count": 1,
    }


def test_session_picker_keeps_row_when_delete_fails() -> None:
    sessions = [_session()]
    screen = SessionPickerScreen(sessions, on_load=lambda _: None, on_delete=lambda _: False)

    async def run() -> None:
        app = _HostApp()
        async with app.run_test(size=(80, 20)) as pilot:
            app.push_screen(screen)
            await pilot.pause()
            screen.on_key(SimpleNamespace(key="d"))
            assert len(sessions) == 1

    import asyncio

    asyncio.run(run())


def test_bash_result_has_separate_command_exit_code_and_output() -> None:
    view = ToolResultView(
        tool_name="bash",
        content="2 passed\n",
        details={"command": "pytest -q", "exit_code": 0},
        is_error=False,
    )

    async def run() -> None:
        app = _ToolResultHost(view)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            command = app.query_one(".tool-result-command", Static)
            exit_code = app.query_one(".tool-result-exit", Static)
            output = app.query_one(".tool-result-output", Static)

            assert isinstance(command.content, Syntax)
            assert "pytest -q" in command.content.code
            assert "0" in str(exit_code.content)
            assert isinstance(output.content, Syntax)
            assert "2 passed" in output.content.code

    import asyncio

    asyncio.run(run())


def test_long_tool_output_is_collapsed_and_can_expand() -> None:
    view = ToolResultView(
        tool_name="bash",
        content="\n".join(f"line {number}" for number in range(20)),
        details={"command": "pytest -vv", "exit_code": 1},
        is_error=True,
    )

    async def run() -> None:
        app = _ToolResultHost(view)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            collapsible = app.query_one(Collapsible)
            assert view.output_is_long
            assert collapsible.collapsed

            collapsible.collapsed = False
            await pilot.pause()
            assert not collapsible.collapsed

    import asyncio

    asyncio.run(run())


def test_read_result_uses_file_extension_for_syntax() -> None:
    assert _output_lexer("read", {"path": "src/app.py"}) == "python"
    assert _output_lexer("read", {"path": "README.unknown"}) == "text"
