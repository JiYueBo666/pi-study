"""tui — 通用终端 UI 封装层。

不依赖 ai / agent_core / coding_agent。tui_app 通过这里使用 TUI 能力，
未来更换底层框架时只需改本包。
"""

from tui.app import TuiApp
from tui.widgets import CommandInput, MessageList, MessageLog, ToolResultView

__all__ = ["TuiApp", "CommandInput", "MessageList", "MessageLog", "ToolResultView"]
