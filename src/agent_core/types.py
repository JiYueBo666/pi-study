import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ai.types import Message, ToolCallContent

AgentMessage = Message


@dataclass(frozen=True, slots=True)
class ToolOutput:
    text: str
    content_type: str = "text"


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    output: ToolOutput
    details: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False
    display_output: ToolOutput | None = None
    context_output: ToolOutput | None = None

    def __init__(
        self,
        output: ToolOutput | str | None = None,
        details: dict[str, Any] | None = None,
        is_error: bool = False,
        display_output: ToolOutput | str | None = None,
        context_output: ToolOutput | str | None = None,
        *,
        content: str | None = None,
    ) -> None:
        """创建工具结果。

        ``content=`` 是迁移期兼容参数；新代码应使用 ``output=ToolOutput(...)``。
        兼容入口集中在这里，避免展示层和 agent core 继续依赖旧字段。
        """

        if output is None:
            output = content
        if output is None:
            raise TypeError("ToolExecutionResult requires output or content")

        object.__setattr__(self, "output", _as_tool_output(output))
        object.__setattr__(self, "details", details or {})
        object.__setattr__(self, "is_error", is_error)
        object.__setattr__(
            self,
            "display_output",
            _as_tool_output(display_output) if display_output is not None else None,
        )
        object.__setattr__(
            self,
            "context_output",
            _as_tool_output(context_output) if context_output is not None else None,
        )

    @property
    def content(self) -> str:
        """迁移期只读兼容属性；新消费者应选择 effective_*_output。"""

        return self.output.text

    @property
    def effective_display_output(self) -> ToolOutput:
        return self.display_output or self.output

    @property
    def effective_context_output(self) -> ToolOutput:
        return self.context_output or self.output


def _as_tool_output(value: ToolOutput | str) -> ToolOutput:
    return value if isinstance(value, ToolOutput) else ToolOutput(value)


# 进度回调
ProgressSink = Callable[[str], None]  # 收到一行文本，返回None


class AgentTool(Protocol):
    """
    Agent 认识的工具协议。实现方是产品层（coding_agent）

    Protocol规定
    只要写了execute方法，就属于AgentTool。而不用强制继承AgentTool
    """

    name: str
    description: str

    async def execute(
        self,
        call: ToolCallContent,
        cancel: asyncio.Event,
        on_progress: ProgressSink | None = None,
    ) -> ToolExecutionResult: ...
