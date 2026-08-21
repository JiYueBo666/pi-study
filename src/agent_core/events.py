"""agent_core.events — 通用 Agent 事件。

03-contracts §2：事件是公开观察机制，消费者可以渲染或记录事件，
但不能用事件修改 Agent 状态。这样 CLI 行为不会反过来变成 Loop 行为。

事件只依赖 ai 层的消息类型，不含任何 Coding 业务概念。
"""

from dataclasses import dataclass

from ai.types import Message, ToolCallContent, ToolResult


@dataclass(frozen=True, slots=True)
class AgentStarted:
    """Agent 开始处理一次用户输入。"""


@dataclass(frozen=True, slots=True)
class AgentEnded:
    """Agent 结束。status 是 03-contracts §2 的一种终态。"""

    status: str  # completed / cancelled / max_turns / model_failed / internal_error


@dataclass(frozen=True, slots=True)
class TurnStarted:
    turn: int


@dataclass(frozen=True, slots=True)
class TurnEnded:
    turn: int


@dataclass(frozen=True, slots=True)
class MessageStarted:
    """消息开始（user / assistant / toolResult）。"""

    message: Message | None = None


@dataclass(frozen=True, slots=True)
class MessageDelta:
    """模型流局部文本增量，仅用于展示，不是持久消息（03-contracts §1）。"""

    delta: str
    partial: str


@dataclass(frozen=True, slots=True)
class ThinkingDeltaEvent:
    """模型思考内容（reasoning）的流式增量。只用于展示，不是持久消息。"""

    delta: str
    partial: str = ""


@dataclass(frozen=True, slots=True)
class MessageCompleted:
    """完整消息加入历史。"""

    message: Message


@dataclass(frozen=True, slots=True)
class ToolStarted:
    call: ToolCallContent


@dataclass(frozen=True, slots=True)
class ToolUpdated:
    """工具执行过程中的部分结果（v0 工具多为一次性返回，partial 通常为 None）。"""

    call: ToolCallContent
    partial: str | None = None


@dataclass(frozen=True, slots=True)
class ToolCompleted:
    call: ToolCallContent
    result: ToolResult


@dataclass(frozen=True, slots=True)
class ContextCompacted:
    summary: str
    retained_count: int


AgentEvent = (
    AgentStarted
    | AgentEnded
    | TurnStarted
    | TurnEnded
    | MessageStarted
    | MessageDelta
    | ThinkingDeltaEvent
    | MessageCompleted
    | ToolStarted
    | ToolUpdated
    | ToolCompleted
    | ContextCompacted
)
