"""tui_app.app - MyPiApp: pi-study 的 TUI 应用。"""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.suggester import SuggestFromList
from textual.widgets import Footer, OptionList, Static

from agent_core.events import (
    AgentEnded,
    ContextCompacted,
    MessageCompleted,
    MessageDelta,
    ThinkingDeltaEvent,
    ToolCompleted,
    ToolStarted,
    ToolUpdated,
    TurnStarted,
)
from ai.types import (
    AssistantMessage,
    CompactionSummaryMessage,
    TextContent,
    ToolResult,
    UserMessage,
)
from tui.app import TuiApp
from tui.widgets import CommandInput, MessageList
from tui_app.controller import TuiController
from tui_app.screens import SessionPickerScreen


class MyPiApp(TuiApp):
    """pi-study 的 Textual TUI 应用。"""

    CSS = """
    Screen {
        background: $background;
        color: $text;
    }
    #app-shell {
        height: 1fr;
        width: 100%;
    }
    #topbar {
        height: 3;
        width: 100%;
        padding: 0 1;
        border-bottom: solid $primary-darken-2;
        background: $surface;
        align: left middle;
    }
    #brand {
        width: 1fr;
        color: $text;
        text-style: bold;
    }
    #session-meta {
        width: auto;
        color: $text-muted;
        content-align: right middle;
    }
    #content {
        height: 1fr;
        min-height: 5;
        padding: 1 0 0 0;
    }
    MessageList {
        height: 1fr;
        border: none;
        background: transparent;
        padding: 0 1;
        scrollbar-color: $primary-darken-1;
    }
    .message {
        width: 100%;
        max-width: 100%;
        margin: 0 0 1 0;
        padding: 0 1;
        background: $panel;
    }
    .message.user {
        border-left: solid $primary;
        background: $surface;
    }
    .message.assistant {
        border-left: solid $accent;
    }
    .message.tool {
        border-left: solid $secondary;
        color: $text-muted;
    }
    .message.thinking {
        border-left: solid $accent-darken-1;
        background: $surface;
        color: $text-muted;
    }
    .message.system {
        border: none;
        background: transparent;
        color: $text-muted;
    }
    #composer {
        height: auto;
        padding: 0 0 1 0;
        border-top: solid $primary-darken-2;
        background: $surface;
    }
    #stream {
        display: none;
        height: auto;
        max-height: 8;
        margin: 0 1;
        padding: 0 1;
        border-left: solid $accent;
        background: $panel;
        color: $text;
    }
    #status {
        height: 1;
        margin: 0 1;
        color: $text-muted;
    }
    #command-palette {
        display: none;
        height: auto;
        max-height: 8;
        margin: 0 1;
        border: solid $secondary;
        background: $panel;
    }
    CommandInput {
        height: 3;
        margin: 0 1;
        border: solid $accent;
        padding: 0 1;
        background: $surface;
    }
    Footer {
        height: 1;
        background: $panel;
    }
    """

    def __init__(self, *, controller: TuiController) -> None:
        super().__init__()
        self.controller = controller
        self.title = "mypi"
        self._stream_kind: str | None = None
        self._stream_partial = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="app-shell"):
            with Horizontal(id="topbar"):
                yield Static("mypi  /  coding agent", id="brand")
                yield Static("新会话", id="session-meta")
            with Vertical(id="content"):
                yield MessageList(id="log")
            with Vertical(id="composer"):
                yield Static("", id="stream")
                yield Static("就绪", id="status")
                yield OptionList(id="command-palette")
                yield CommandInput(id="input", placeholder="输入消息，或以 / 开始命令")
        yield Footer()

    def on_mount(self) -> None:
        self.controller.subscribe(self._on_agent_event)
        self._refresh_session_meta()
        self.query_one(MessageList).add_message("已就绪 · 当前工作区可直接交给 agent", role="system")

        input_widget = self.query_one(CommandInput)
        input_widget.suggester = SuggestFromList([f"/{name}" for name in self.controller.registry.command_names()])
        input_widget.focus()

    def on_input_submitted(self, event: CommandInput.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        self.query_one(CommandInput).value = ""

        if text.startswith("/"):
            palette = self.query_one("#command-palette", OptionList)
            if palette.display:
                index = palette.highlighted
                if index is not None:
                    text = str(palette.get_option_at_index(index).prompt)
                palette.display = False
            self._handle_command(text)
            return

        self.query_one("#command-palette", OptionList).display = False
        self.query_one(MessageList).add_message(text, role="user")
        self._set_status("处理中")
        self.run_worker(self._run_prompt(text), exclusive=True, group="agent")

    # ---- 命令补全弹窗 ----

    def on_input_changed(self, event: CommandInput.Changed) -> None:
        self._update_command_palette(event.value)

    def _update_command_palette(self, value: str) -> None:
        palette = self.query_one("#command-palette", OptionList)
        if not value.startswith("/"):
            palette.display = False
            return

        matches = self.controller.registry.complete(value)
        palette.clear_options()
        for name in matches:
            palette.add_option(f"/{name}")
        palette.display = bool(matches)
        if matches:
            palette.highlighted = 0
            palette.scroll_to_highlight()

    def on_command_input_palette_down(self, event: CommandInput.PaletteDown) -> None:
        self._move_palette(1)

    def on_command_input_palette_up(self, event: CommandInput.PaletteUp) -> None:
        self._move_palette(-1)

    def on_command_input_palette_select(self, event: CommandInput.PaletteSelect) -> None:
        self.query_one("#command-palette", OptionList).display = False

    def _move_palette(self, delta: int) -> None:
        palette = self.query_one("#command-palette", OptionList)
        if not palette.display or palette.option_count == 0:
            return
        index = palette.highlighted
        if index is None:
            index = 0
        palette.highlighted = (index + delta) % palette.option_count
        palette.scroll_to_highlight()

    # ---- 命令执行 ----

    def _handle_command(self, text: str) -> None:
        async def run() -> None:
            result = await self.controller.run_command(text)
            log = self.query_one(MessageList)
            data = result.data or {}
            action = data.get("action")
            sessions = data.get("sessions") or []
            if result.message and action not in {"list", "deleted"}:
                log.add_message(result.message, role="system")
            if action == "list":
                if sessions:
                    self._show_session_picker(sessions)
                else:
                    log.add_message(result.message or "暂无已保存会话", role="system")
            elif action == "load":
                await self._load_session(data["session_id"])
            elif action == "deleted":
                log.add_message("会话已删除", role="system")

            if result.should_exit:
                self.exit()

        self.run_worker(run(), exclusive=True, group="command")

    async def _run_prompt(self, text: str) -> None:
        input_widget = self.query_one(CommandInput)
        input_widget.disabled = True
        try:
            await self.controller.run_prompt(text)
        except Exception as exc:
            self.query_one(MessageList).add_message(f"错误: {exc}", role="system")
        finally:
            input_widget.disabled = False
            input_widget.focus()
            self._refresh_session_meta()
            self._set_status("就绪")

    # ---- 会话管理 ----

    def _show_session_picker(self, sessions: list[dict]) -> None:
        screen = SessionPickerScreen(
            sessions=sessions,
            on_load=lambda sid: self.run_worker(self._load_session(sid)),
            on_delete=self._delete_session,
        )
        self.push_screen(screen)

    async def _load_session(self, session_id: str) -> None:
        try:
            await self.controller.load_session(session_id)
            self._render_history()
            self._refresh_session_meta()
            self.query_one(MessageList).add_message(f"已载入会话 {session_id}", role="system")
        except Exception as exc:
            self.query_one(MessageList).add_message(f"载入失败: {exc}", role="system")

    def _delete_session(self, session_id: str) -> bool:
        try:
            self.controller.delete_session(session_id)
            return True
        except Exception as exc:
            self.query_one(MessageList).add_message(f"删除失败: {exc}", role="system")
            return False

    def _render_history(self) -> None:
        log = self.query_one(MessageList)
        log.clear_messages()
        session_id = self.controller.session.session_id or "新会话"
        log.add_message(f"会话 {session_id}", role="system")
        for message in self.controller.session.messages:
            self._render_message(log, message, include_user=True)

    def _refresh_session_meta(self) -> None:
        session_id = self.controller.session.session_id or "新会话"
        workspace = self.controller.workspace.name or str(self.controller.workspace)
        self.query_one("#session-meta", Static).update(f"{workspace}  ·  {session_id}")

    def _set_status(self, value: str) -> None:
        self.query_one("#status", Static).update(value)

    # ---- 流式渲染 ----

    def _stream(self, partial: str, kind: str) -> None:
        if self._stream_kind and self._stream_kind != kind:
            self._finish_stream()
        stream = self.query_one("#stream", Static)
        stream.display = True
        prefix = "思考  " if kind == "thinking" else ""
        stream.update(f"{prefix}{partial}")
        self._stream_kind = kind
        self._stream_partial = partial

    def _finish_stream(self) -> None:
        stream = self.query_one("#stream", Static)
        if not stream.display:
            return
        if self._stream_kind == "thinking" and self._stream_partial:
            self.query_one(MessageList).add_message(self._stream_partial, role="thinking")
        stream.display = False
        stream.update("")
        self._stream_kind = None
        self._stream_partial = ""

    # ---- Agent 事件渲染 ----

    def _on_agent_event(self, event) -> None:
        log = self.query_one(MessageList)
        status = self.query_one("#status", Static)

        if isinstance(event, TurnStarted):
            self._finish_stream()
            log.add_message(f"轮次 {event.turn}", role="system")
        elif isinstance(event, ThinkingDeltaEvent):
            self._stream(event.partial, kind="thinking")
            status.update("思考中")
        elif isinstance(event, MessageDelta):
            self._stream(event.partial, kind="assistant")
            status.update("生成中")
        elif isinstance(event, ToolStarted):
            self._finish_stream()
            log.add_message(f"运行工具  {event.call.name}({event.call.arguments})", role="tool")
            status.update(f"运行中 · {event.call.name}")
        elif isinstance(event, ToolUpdated):
            status.update(f"运行中 · {event.partial or event.call.name}")
        elif isinstance(event, ToolCompleted):
            self._finish_stream()
            mark = "✓" if not event.result.isError else "✗"
            log.add_message(f"{mark}  工具 {event.call.name}", role="tool")
            status.update("处理中")
        elif isinstance(event, MessageCompleted):
            self._finish_stream()
            status.update("处理中")
            self._render_message(log, event.message)
        elif isinstance(event, ContextCompacted):
            self._finish_stream()
            log.add_message(f"[上下文已压缩 · 保留 {event.retained_count} 条最近消息]", role="system")
        elif isinstance(event, AgentEnded):
            self._finish_stream()
            status.update("就绪" if event.status == "completed" else event.status)
            log.add_message(f"任务 {event.status}", role="system")

    def _render_message(self, log: MessageList, message, *, include_user: bool = False) -> None:
        text = self._message_text(message, include_user=include_user)
        if text:
            role = self._message_role(message, include_user=include_user)
            log.add_message(text, role=role)

    def _message_text(self, message, *, include_user: bool = False) -> str | None:
        if isinstance(message, UserMessage):
            return message.content if include_user else None
        if isinstance(message, AssistantMessage):
            text = "".join(b.text for b in message.content if isinstance(b, TextContent))
            return text or None
        if isinstance(message, ToolResult):
            content = "".join(b.text for b in message.content if isinstance(b, TextContent))
            return f"{message.toolName}: {content[:200]}"
        if isinstance(message, CompactionSummaryMessage):
            return f"[上下文摘要] {message.summary[:200]}"
        return None

    def _message_role(self, message, *, include_user: bool = False) -> str:
        if isinstance(message, UserMessage):
            return "user" if include_user else "system"
        if isinstance(message, AssistantMessage):
            return "assistant"
        if isinstance(message, ToolResult):
            return "tool"
        if isinstance(message, CompactionSummaryMessage):
            return "thinking"
        return "system"
