"""tui.widgets — 项目基础组件。"""

from pathlib import Path
from typing import Any

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Collapsible, Input, Static

LONG_OUTPUT_LINES = 12
LONG_OUTPUT_CHARS = 1200

_LEXER_BY_SUFFIX = {
    ".css": "css",
    ".html": "html",
    ".ini": "ini",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "jsx",
    ".md": "markdown",
    ".py": "python",
    ".sh": "bash",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


class CommandInput(Input):
    """消息 / 命令输入框。

    - Tab：接受当前补全建议
    - Up / Down：在命令弹窗中移动选择
    """

    BINDINGS = [
        *Input.BINDINGS,
        Binding("tab", "accept_suggestion", "Complete", show=False),
        Binding("down", "palette_down", "Next", show=False),
        Binding("up", "palette_up", "Previous", show=False),
    ]

    class PaletteDown(Message):
        """向下移动命令弹窗选择。"""

    class PaletteUp(Message):
        """向上移动命令弹窗选择。"""

    class PaletteSelect(Message):
        """选择命令弹窗当前项。"""

    def action_accept_suggestion(self) -> None:
        if getattr(self, "_suggestion", None):
            self.action_cursor_right()
        self.post_message(self.PaletteSelect())

    def action_palette_down(self) -> None:
        self.post_message(self.PaletteDown())

    def action_palette_up(self) -> None:
        self.post_message(self.PaletteUp())


class ToolResultView(Vertical):
    """结构化展示一次工具执行结果。"""

    def __init__(
        self,
        *,
        tool_name: str,
        content: str,
        details: dict[str, Any],
        is_error: bool,
    ) -> None:
        state = "error" if is_error else "success"
        super().__init__(classes=f"tool-result {state}")
        self.tool_name = tool_name
        self.content = content
        self.details = details
        self.is_error = is_error

    @property
    def output_is_long(self) -> bool:
        return _is_long_output(self.content)

    def compose(self) -> ComposeResult:
        mark = "✗" if self.is_error else "✓"
        yield Static(f"{mark}  {self.tool_name}", classes="tool-result-header")

        if self.tool_name == "bash":
            command = str(self.details.get("command", ""))
            if command:
                yield Static("COMMAND", classes="tool-result-label")
                yield Static(
                    _syntax(command, "bash"),
                    classes="tool-result-command",
                )

            exit_code = self.details.get("exit_code")
            exit_text = "—" if exit_code is None else str(exit_code)
            if self.details.get("timed_out"):
                exit_text = f"{exit_text}  ·  timed out"
            yield Static(
                f"EXIT CODE  {exit_text}",
                classes="tool-result-exit",
            )

        path = self.details.get("path")
        if path and self.tool_name != "bash":
            yield Static(str(path), classes="tool-result-path")

        output = self.content.rstrip("\n") or "(no output)"
        output_view = Static(
            _syntax(output, _output_lexer(self.tool_name, self.details)),
            classes="tool-result-output",
        )
        line_count = max(1, len(output.splitlines()))
        if self.output_is_long:
            yield Collapsible(
                output_view,
                title=f"OUTPUT  ·  {line_count} lines",
                collapsed=True,
                classes="tool-result-collapsible",
            )
        else:
            yield Static("OUTPUT", classes="tool-result-label")
            yield output_view


def _syntax(code: str, lexer: str) -> Syntax:
    return Syntax(
        code,
        lexer,
        theme="ansi_dark",
        word_wrap=True,
        background_color="default",
        padding=(0, 1),
    )


def _is_long_output(content: str) -> bool:
    return len(content) > LONG_OUTPUT_CHARS or len(content.splitlines()) > LONG_OUTPUT_LINES


def _output_lexer(tool_name: str, details: dict[str, Any]) -> str:
    if tool_name == "bash":
        return "console"
    path = details.get("path")
    if isinstance(path, str):
        return _LEXER_BY_SUFFIX.get(Path(path).suffix.lower(), "text")
    return "text"


class MessageList(VerticalScroll):
    """消息列表：按角色分层展示消息，保持流式输出稳定。"""

    def add_message(self, text: str, *, role: str = "system") -> None:
        message = Static(text, classes=f"message {role}")
        self.mount(message)
        self.scroll_end(animate=False)

    def add_tool_result(
        self,
        *,
        tool_name: str,
        content: str,
        details: dict[str, Any],
        is_error: bool,
    ) -> None:
        self.mount(
            ToolResultView(
                tool_name=tool_name,
                content=content,
                details=details,
                is_error=is_error,
            )
        )
        self.scroll_end(animate=False)

    def update_last(self, text: str) -> None:
        if self.children and isinstance(self.children[-1], Static):
            self.children[-1].update(text)

    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()


# 保留 RichLog 别名，避免已有引用出错
MessageLog = MessageList
