"""AI 层 — 统一模型调用，不关心 Agent 逻辑。

职责：模型选择、请求消息、流式输出、工具格式封装、token 记录、适配供应商。
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel

Role = Literal["system", "user", "assistant", "toolResult", "compactionSummary"]
ContentType = Literal["thinking", "text", "toolCall"]

# 占位类型：字段注释已声明意图，具体取值随 Provider 适配（Phase 1/2）确定。
Api = str  # 使用的 api 类型，例如 "anthropic-messages"
ProviderID = str  # 提供商，例如 "openai"
Usage = dict[str, Any]  # token 用量
StopReason = str  # 停止原因，例如 "stop" / "tool_use" / "length"
TDetails = dict  # 给 UI 看的结构化详情


# 文本内容
@dataclass(frozen=True, slots=True)
class TextContent:
    text: str
    type: ContentType = "text"


# 思考内容
@dataclass(frozen=True, slots=True)
class ThinkingContent:
    thinking: str
    type: ContentType = "thinking"


# 工具调用内容
@dataclass(frozen=True, slots=True)
class ToolCallContent:
    id: str
    name: str
    arguments: dict[str, Any]
    type: ContentType = "toolCall"


@dataclass(frozen=True, slots=True)
class UserMessage:
    content: str
    timestamp: datetime
    role: Role = "user"


@dataclass(frozen=True, slots=True)
class AssistantMessage:
    content: list[TextContent | ThinkingContent | ToolCallContent]
    timestamp: datetime
    api: Api  # 使用的api类型，例如anthropic-messages
    provider: ProviderID  # 提供商，例如OpenAI
    model: str  # 模型名称
    usage: Usage  # 用量
    stopReason: StopReason  # 停止原因
    role: Role = "assistant"
    errorMessage: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    toolCallId: str
    toolName: str
    content: list[TextContent]
    details: TDetails  # 给UI看的结构化内容
    timestamp: datetime
    isError: bool = False  # 是否执行失败
    role: Role = "toolResult"


@dataclass(frozen=True, slots=True)
class CompactionSummaryMessage:
    summary: str
    timestamp: datetime
    tokens_before: int = 0
    role: Role = "compactionSummary"




Message = UserMessage | AssistantMessage | ToolResult | CompactionSummaryMessage


# -----------模型流事件
@dataclass(frozen=True, slots=True)
class StreamStarted:
    """
    流开始
    """


@dataclass(frozen=True, slots=True)
class TextDelta:
    delta: str
    partial: str


@dataclass(frozen=True, slots=True)
class ThinkingDelta:
    """模型思考内容的流式增量（对应 pi 的 thinking_delta）。"""

    delta: str
    partial: str = ""


@dataclass(frozen=True, slots=True)
class ToolCallDelta:
    """工具调用的一个片段；id/name 只在首个片段出现。"""

    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass(frozen=True, slots=True)
class StreamCompleted:
    message: AssistantMessage


@dataclass(frozen=True, slots=True)
class StreamFailed:
    error: str
    message: AssistantMessage | None = None  # 失败前已流出的部分


StreamEvent = (
    StreamStarted
    | ThinkingDelta
    | TextDelta
    | ToolCallDelta
    | StreamCompleted
    | StreamFailed
)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    id: str
    provider: ProviderID = "openai"
    api: Api = "openai-completions"
    # 由产品组装层按实际部署模型配置；未知时不猜测固定窗口。
    context_window: int | None = None
    # 单次回答允许的最大输出，用于从总窗口计算可用输入预算。
    max_output_tokens: int | None = None

    def input_token_limit(self, fallback_reserve_tokens: int) -> int | None:
        """返回可用输入 token 上限；没有真实窗口时返回 None。"""

        if self.context_window is None:
            return None
        reserve = self.max_output_tokens if self.max_output_tokens is not None else fallback_reserve_tokens
        return max(0, self.context_window - reserve)


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    parameter_model: type[BaseModel] | None = None

    @classmethod
    def from_model(
        cls, *, name: str, description: str, parameter_model: type[BaseModel]
    ) -> Self:
        """从 Pydantic 参数模型生成 provider 所需的 JSON Schema。"""
        return cls(
            name=name,
            description=description,
            parameters=parameter_model.model_json_schema(),
            parameter_model=parameter_model,
        )


@dataclass(frozen=True, slots=True)
class ModelContext:
    model: ModelConfig
    system_prompt: str | None = None  # ← 默认 None
    messages: Sequence[Message] = ()  # ← 默认空元组
    tools: Sequence[ToolDefinition] = ()  # ← 默认空元组


def prompt_tokens(usage: Mapping[str, Any]) -> int | None:
    """读取供应商归一化后的请求输入 token 数。"""

    value = usage.get("prompt_tokens")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
