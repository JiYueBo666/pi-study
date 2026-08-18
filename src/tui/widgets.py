"""tui.widgets — 项目基础组件。"""

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Input, Static


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


class MessageList(VerticalScroll):
    """消息列表：按角色分层展示消息，保持流式输出稳定。"""

    def add_message(self, text: str, *, role: str = "system") -> None:
        message = Static(text, classes=f"message {role}")
        self.mount(message)
        self.scroll_end(animate=False)

    def update_last(self, text: str) -> None:
        if self.children and isinstance(self.children[-1], Static):
            self.children[-1].update(text)

    def clear_messages(self) -> None:
        for child in list(self.children):
            child.remove()


# 保留 RichLog 别名，避免已有引用出错
MessageLog = MessageList
