import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ai.types import Message, ToolCallContent

AgentMessage = Message


@dataclass(frozen=True, slots=True)
class ToolExecutionResult:
    content: str
    details: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False


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
