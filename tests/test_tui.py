"""TUI 状态行为测试。"""

from types import SimpleNamespace

from textual.app import App, ComposeResult
from textual.widgets import Static

from tui_app.screens import SessionPickerScreen


class _HostApp(App):
    def compose(self) -> ComposeResult:
        yield Static("host")


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
