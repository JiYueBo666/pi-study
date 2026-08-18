"""tui_app.screens - TUI 弹窗界面。"""

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, ListItem, ListView


class SessionPickerScreen(ModalScreen):
    """会话选择弹窗：Enter 载入，D 删除，Esc 关闭。"""

    CSS = """
    SessionPickerScreen {
        align: center middle;
        background: $background 80%;
    }
    #session-dialog {
        width: 90%;
        max-width: 96;
        height: 70%;
        max-height: 24;
        padding: 1 2;
        border: round $primary;
        background: $surface;
    }
    #session-title {
        color: $text;
        text-style: bold;
    }
    #session-subtitle {
        height: 1;
        margin: 0 0 1 0;
        color: $text-muted;
    }
    #session-list {
        height: 1fr;
        border: solid $primary-darken-2;
        background: $panel;
    }
    #session-list ListItem {
        height: 3;
        padding: 0 1;
        border-bottom: solid $primary-darken-2;
    }
    #session-list ListItem.--highlight {
        background: $primary-darken-2;
        color: $text;
    }
    #session-list .empty {
        color: $text-muted;
    }
    #session-hint {
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
    }
    Footer {
        height: 1;
        background: transparent;
    }
    """

    def __init__(self, sessions, on_load, on_delete) -> None:
        super().__init__()
        self.sessions = sessions
        self.on_load = on_load
        self.on_delete = on_delete

    def compose(self) -> ComposeResult:
        with Vertical(id="session-dialog"):
            yield Label("会话", id="session-title")
            yield Label("选择一条历史记录继续工作", id="session-subtitle")
            yield ListView(id="session-list")
            yield Label("Enter 载入    D 删除    Esc 关闭", id="session-hint")
        yield Footer()

    def on_mount(self) -> None:
        self._populate()

    def _populate(self) -> None:
        list_view = self.query_one("#session-list", ListView)
        list_view.clear()
        if not self.sessions:
            list_view.append(ListItem(Label("暂无已保存会话"), classes="empty"))
            return
        for session in self.sessions:
            updated = session["updated_at"].replace("T", " ")[:16]
            cwd = session.get("cwd", "").rstrip("/").rsplit("/", 1)[-1] or "工作区"
            list_view.append(
                ListItem(Label(f"{session['id']}  ·  {updated}  ·  {session['message_count']} 条消息  ·  {cwd}"))
            )

    @on(ListView.Selected)
    def _selected(self, event: ListView.Selected) -> None:
        list_view = self.query_one("#session-list", ListView)
        index = list_view.index
        if index is not None and 0 <= index < len(self.sessions):
            session_id = self.sessions[index]["id"]
            self.on_load(session_id)
            self.dismiss()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
        elif event.key.lower() == "d":
            list_view = self.query_one("#session-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self.sessions):
                session_id = self.sessions[index]["id"]
                if self.on_delete(session_id):
                    self.sessions.pop(index)
                    self._populate()
