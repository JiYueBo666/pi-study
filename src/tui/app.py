"""tui.app — TUI 应用基类。"""

from textual.app import App


class TuiApp(App):
    """项目 TUI 基类。

    未来公共主题、键位、生命周期逻辑都收敛到这里。
    """
