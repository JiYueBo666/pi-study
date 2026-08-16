"""coding_agent.render — 终端事件渲染器。

设计原则（02-architecture / 03-contracts）：
- 渲染器是纯事件消费者：只 import 事件 dataclass，不接触 Agent 状态；
- 未来 tui 包可平行替换本模块——事件订阅接口是两者共同的不动点；
- 无 TUI 框架依赖，纯 ANSI 转义 + 标准输出。
"""

from agent_core.events import (
    AgentEnded,
    MessageDelta,
    ThinkingDeltaEvent,
    ToolCompleted,
    ToolStarted,
    ToolUpdated,
    TurnStarted,
)

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"

_ENDED_LABELS = {
    "completed": ("✓ completed", GREEN),
    "cancelled": ("⊘ cancelled", YELLOW),
    "max_turns": ("⚠ max_turns", YELLOW),
    "model_failed": ("✗ model_failed", RED),
    "internal_error": ("✗ internal_error", RED),
}


class TerminalRenderer:
    """把 AgentEvent 渲染成终端画面。

    - MessageDelta：流式打印模型文本（阶段说明 + 最终回答）
    - ToolStarted：`▶ name(参数摘要)`
    - ToolCompleted：一行结果徽章（✓ 行数 / exit 码 / ✗ 错误）
    - AgentEnded：终态徽章
    """

    def __init__(self, *, color: bool = True) -> None:
        self._color = color
        self._streaming = False  # 模型文本流式打印中
        self._thinking = False  # 模型思考流式打印中

    # 作为同步监听器订阅给 Agent（返回 None）
    def __call__(self, event: object) -> None:
        if isinstance(event, ThinkingDeltaEvent):
            self._on_thinking(event)
        elif isinstance(event, MessageDelta):
            self._on_delta(event)
        elif isinstance(event, ToolStarted):
            self._on_tool_started(event)
        elif isinstance(event, ToolCompleted):
            self._on_tool_completed(event)
        elif isinstance(event, TurnStarted):
            self._on_turn(event)
        elif isinstance(event, AgentEnded):
            self._on_ended(event)
        elif isinstance(event, ToolUpdated):
            self._on_tool_updated(event)
        # 其余事件：v0 不渲染

    def _print(self, text: str = "", *, end: str = "\n") -> None:
        print(text, end=end, flush=True)

    def _paint(self, text: str, code: str) -> str:
        if not self._color:
            return text
        return f"{code}{text}{RESET}"

    def _break_stream(self) -> None:
        if self._streaming or self._thinking:
            self._print()
            self._streaming = False
            self._thinking = False

    # ---- 事件处理 ----

    def _on_thinking(self, event: ThinkingDeltaEvent) -> None:
        if not self._thinking:
            self._break_stream()
            self._print(self._paint("💭 ", DIM), end="")
            self._thinking = True
        self._print(self._paint(event.delta, DIM), end="")

    def _on_delta(self, event: MessageDelta) -> None:
        if self._thinking:
            self._break_stream()  # 思考结束，正文另起一行
        self._print(event.delta, end="")
        self._streaming = True

    def _on_turn(self, event: TurnStarted) -> None:
        self._break_stream()
        self._print(self._paint(f"── 轮次 {event.turn} ──", DIM))

    def _on_tool_started(self, event: ToolStarted) -> None:
        self._break_stream()
        args = _arg_summary(event.call.arguments)
        self._print(f"▶ {self._paint(event.call.name, CYAN)}({args})")

    def _on_tool_completed(self, event: ToolCompleted) -> None:
        text = _result_text(event.result)
        if event.result.isError:
            reason = _first_line(text) or "unknown error"
            self._print(f"  {self._paint('✗', RED)} {reason[:80]}")
            return
        summary = _result_summary(event.call.name, event.result, text)
        self._print(f"  {self._paint('✓', GREEN)} {summary}")

    def _on_ended(self, event: AgentEnded) -> None:
        self._break_stream()
        label, code = _ENDED_LABELS.get(event.status, (event.status, DIM))
        self._print(self._paint(label, code))

    def _on_tool_updated(self, event: ToolUpdated):
        self._print(self._paint(f"  │ {event.partial}", DIM))


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def _result_text(result: object) -> str:
    """ToolResult.content 是 list[TextContent]，取文本块拼接。"""

    content = getattr(result, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.text for b in content if getattr(b, "type", None) == "text")
    return str(content)


def _arg_summary(arguments: dict) -> str:
    """参数摘要：长文本/多行文本只显示概要，避免刷屏。"""

    parts: list[str] = []
    for key, value in arguments.items():
        if isinstance(value, str):
            if "\n" in value:
                parts.append(f"{key}='<{len(value.splitlines())} 行内容>'")
            elif len(value) > 60:
                parts.append(f"{key}='{value[:60]}…'（{len(value)} 字符）")
            else:
                parts.append(f"{key}={value!r}")
        else:
            parts.append(f"{key}={value!r}")
    return ", ".join(parts)


def _result_summary(tool_name: str, result: object, text: str) -> str:
    """工具结果一行摘要。"""

    details = getattr(result, "details", {})

    if tool_name == "bash":
        code = details.get("exit_code")
        if details.get("timed_out"):
            return f"⏱ 超时终止 (exit {code})"
        return f"exit {code}"

    if tool_name == "read":
        lines = len(text.splitlines())
        suffix = "（已截断）" if details.get("truncated") else ""
        return f"{lines} 行{suffix}"

    if tool_name in {"write", "edit"}:
        return _first_line(text) or "ok"

    lines = len(text.splitlines())
    suffix = "（已截断）" if details.get("truncated") else ""
    return f"{lines} 条{suffix}"
