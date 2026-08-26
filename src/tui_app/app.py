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
    SteeringQueued,
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
from coding_agent.event import (
    ToolApprovalCompleted,
    ToolApprovalRequest,
    ToolApprovalRequested,
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
    .message.approval {
        border: solid $warning;
        background: $surface;
        color: $text;
        text-style: bold;
    }
    .message.steering {
        border: solid $warning;
        border-left: wide $warning;
        background: $surface;
        color: $warning;
        text-style: bold;
    }
    .message.error {
        border-left: wide $error;
        background: $surface;
        color: $error;
    }
    ToolResultView {
        width: 100%;
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1 1 1;
        border-left: solid $secondary;
        background: $panel;
    }
    ToolResultView.error {
        border-left: solid $error;
    }
    .tool-result-header {
        height: 1;
        margin: 0 0 1 0;
        color: $success;
        text-style: bold;
    }
    ToolResultView.error .tool-result-header {
        color: $error;
    }
    .tool-result-label {
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
        text-style: bold;
    }
    .tool-result-command, .tool-result-output {
        width: 100%;
        height: auto;
        background: $surface;
    }
    .tool-result-exit {
        height: 1;
        margin: 1 0 0 0;
        color: $text-muted;
    }
    .tool-result-path {
        height: 1;
        color: $text-muted;
    }
    .tool-result-collapsible {
        width: 100%;
        height: auto;
        margin: 1 0 0 0;
        padding: 0;
        background: $surface;
        border-top: solid $primary-darken-2;
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
        self._pending_approval: ToolApprovalRequest | None = None
        self._agent_running = False

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

        if self._pending_approval is not None:
            self._handle_approval_input(text)
            return

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
        if self._agent_running:
            if self.controller.steer(text):
                self._set_status("已加入下一轮")
            else:
                self.query_one(MessageList).add_message("插队队列已满，请等待当前任务继续", role="system")
            return

        self.query_one(MessageList).add_message(text, role="user")
        self._set_status("处理中")
        self._agent_running = True
        self.run_worker(self._run_prompt(text), exclusive=True, group="agent")

    # ---- 工具审批 ----

    def _handle_approval_input(self, text: str) -> None:
        request = self._pending_approval
        if request is None:
            return

        value = text.strip().lower()
        log = self.query_one(MessageList)
        if value in ("y", "yes"):
            self.controller.resolve_approval(request.request_id, True)
            self._pending_approval = None
            log.add_message("已批准工具调用", role="system")
            self._set_status("已批准 · 继续执行")
            self.query_one(CommandInput).disabled = True
        elif value in ("n", "no"):
            self.controller.resolve_approval(request.request_id, False)
            self._pending_approval = None
            log.add_message("已拒绝工具调用", role="system")
            self._set_status("已拒绝")
            self.query_one(CommandInput).disabled = True
        else:
            log.add_message("请输入 y 或 n", role="system")
            self.query_one(CommandInput).focus()

    def _show_approval_prompt(self, request: ToolApprovalRequest) -> None:
        self._pending_approval = request
        args = request.call.arguments
        lines = [
            "⚠️  工具调用需要审批",
            "",
            f"工具：{request.tool_name}",
            f"说明：{request.tool_description}",
            f"参数：{args}",
            "",
            "允许执行？输入 y / n",
        ]
        self.query_one(MessageList).add_message("\n".join(lines), role="approval")
        input_widget = self.query_one(CommandInput)
        input_widget.disabled = False
        input_widget.focus()
        self._set_status("等待审批 y/n")

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
            if action == "clear":
                self._finish_stream()
                log.clear_messages()
                self._set_status("消息区已清空")
            elif result.message and action not in {"list", "deleted"}:
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
            elif action == "model_changed":
                self._refresh_session_meta()

            if result.should_exit:
                self.exit()

        self.run_worker(run(), exclusive=True, group="command")

    async def _run_prompt(self, text: str) -> None:
        input_widget = self.query_one(CommandInput)
        try:
            await self.controller.run_prompt(text)
        except Exception as exc:
            self.query_one(MessageList).add_message(f"错误: {exc}", role="system")
        finally:
            self._agent_running = False
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
        model_id = self.controller.session.model.id
        workspace = self.controller.workspace.name or str(self.controller.workspace)
        self.query_one("#session-meta", Static).update(f"{workspace}  ·  {session_id}  ·  {model_id}")

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
        elif isinstance(event, SteeringQueued):
            self._finish_stream()
            for message in event.messages:
                log.add_message(
                    f"插队消息 · 下一轮 {event.turn + 1}\n{message.content}",
                    role="steering",
                )
            status.update(f"已插入下一轮 · {len(event.messages)} 条消息")
        elif isinstance(event, ThinkingDeltaEvent):
            self._stream(event.partial, kind="thinking")
            status.update("思考中")
        elif isinstance(event, MessageDelta):
            self._stream(event.partial, kind="assistant")
            status.update("生成中")
        elif isinstance(event, ToolStarted):
            self._finish_stream()
            status.update(f"运行中 · {event.call.name}")
        elif isinstance(event, ToolUpdated):
            status.update(f"运行中 · {event.partial or event.call.name}")
        elif isinstance(event, ToolApprovalRequested):
            self._finish_stream()
            self._show_approval_prompt(event.request)
        elif isinstance(event, ToolApprovalCompleted):
            self._pending_approval = None
            status.update("已批准" if event.approved else "已拒绝")
        elif isinstance(event, ToolCompleted):
            self._finish_stream()
            if event.display is not None:
                log.add_tool_result(
                    tool_name=event.display.tool_name,
                    content=event.display.output.text,
                    details=event.display.details,
                    is_error=event.display.is_error,
                )
            status.update("处理中")
        elif isinstance(event, MessageCompleted):
            self._finish_stream()
            status.update("处理中")
            # 工具结果由 ToolCompleted 携带展示输出渲染。这样模型上下文
            # 可以是截断版，而 TUI 仍能展示完整输出。
            if not isinstance(event.message, ToolResult):
                self._render_message(log, event.message)
        elif isinstance(event, ContextCompacted):
            self._finish_stream()
            log.add_message(f"[上下文已压缩 · 保留 {event.retained_count} 条最近消息]", role="system")
        elif isinstance(event, AgentEnded):
            self._finish_stream()
            if event.error:
                title = "模型调用失败" if event.status == "model_failed" else "Agent 内部错误"
                status.update(title)
                log.add_message(
                    f"{title}\n{event.error}",
                    role="error",
                )
            else:
                status.update("就绪" if event.status == "completed" else event.status)
                log.add_message(f"任务 {event.status}", role="system")

    def _render_message(self, log: MessageList, message, *, include_user: bool = False) -> None:
        if isinstance(message, ToolResult):
            content = "".join(b.text for b in message.content if isinstance(b, TextContent))
            log.add_tool_result(
                tool_name=message.toolName,
                content=content,
                details=message.details,
                is_error=message.isError,
            )
            return

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
        if isinstance(message, CompactionSummaryMessage):
            return f"[上下文摘要] {message.summary[:200]}"
        return None

    def _message_role(self, message, *, include_user: bool = False) -> str:
        if isinstance(message, UserMessage):
            return "user" if include_user else "system"
        if isinstance(message, AssistantMessage):
            return "assistant"
        if isinstance(message, CompactionSummaryMessage):
            return "thinking"
        return "system"
