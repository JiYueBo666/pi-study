"""agent_core.compaction — 上下文压缩。

当对话历史超过阈值时，把旧消息摘要成一条 CompactionSummaryMessage，
保留最近轮次原文，确保下次模型调用不会超长。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from ai.types import (
    AssistantMessage,
    CompactionSummaryMessage,
    Message,
    ModelConfig,
    ModelContext,
    StreamCompleted,
    StreamFailed,
    TextContent,
    ThinkingContent,
    ToolCallContent,
    ToolResult,
    UserMessage,
    prompt_tokens,
)

SUMMARIZATION_SYSTEM_PROMPT = """You are a context summarization assistant. Your task is to read a conversation
between a user and an AI assistant, then produce a structured summary following the exact format specified.

Do NOT continue the conversation. Do NOT respond to any questions in the conversation.
ONLY output the structured summary."""

SUMMARIZATION_PROMPT = """Create a structured context checkpoint summary that another LLM will use to continue the work.

Use this EXACT format:

## Goal
[What is the user trying to accomplish?]

## Progress
### Done
- [x] [Completed tasks/changes]

### In Progress
- [ ] [Current work]

### Blocked
- [Issues preventing progress, if any]

## Key Decisions
- **[Decision]**: [Brief rationale]

## Next Steps
1. [Ordered list of what should happen next]

## Critical Context
- [Any data, examples, or references needed to continue]

Keep each section concise. Preserve exact file paths, function names, and error messages."""


@dataclass(frozen=True, slots=True)
class CompactionSettings:
    enabled: bool = True
    reserve_tokens: int = 16_000
    keep_recent_turns: int = 1


class CompactionError(Exception):
    """摘要生成失败等压缩错误。"""


def latest_prompt_tokens(messages: Sequence[Message]) -> int | None:
    """返回最近一次模型调用实际接收的 prompt token 数。"""

    for message in reversed(messages):
        if isinstance(message, AssistantMessage):
            tokens = prompt_tokens(message.usage)
            if tokens is not None:
                return tokens
    return None


def input_token_limit(model: ModelConfig, settings: CompactionSettings) -> int | None:
    """由真实模型窗口和输出预留得到输入上限，未知时不自动压缩。"""

    return model.input_token_limit(settings.reserve_tokens)


def should_compact(messages: Sequence[Message], model: ModelConfig, settings: CompactionSettings) -> bool:
    """仅在 Provider usage 与模型窗口都已知时自动压缩。"""

    usage = latest_prompt_tokens(messages)
    limit = input_token_limit(model, settings)
    return usage is not None and limit is not None and usage > limit


def find_cut_index(messages: Sequence[Message], keep_recent_turns: int) -> int:
    """按轮次边界找切点。

    只允许在 UserMessage 开头切，避免拆散 AssistantMessage(tool_calls)
    和它对应的 ToolResult。返回保留 tail 的起始索引；返回 0 表示不压缩。
    """
    user_indices = [i for i, m in enumerate(messages) if isinstance(m, UserMessage)]
    if not user_indices:
        return 0

    if keep_recent_turns < 1 or len(user_indices) <= keep_recent_turns:
        return 0
    return user_indices[-keep_recent_turns]


def serialize_messages(messages: Sequence[Message]) -> str:
    """把消息列表序列化成摘要 prompt 可读的纯文本。"""
    lines: list[str] = []
    for m in messages:
        if isinstance(m, UserMessage):
            lines.append(f"User: {m.content}")
        elif isinstance(m, AssistantMessage):
            parts: list[str] = []
            thinking = "".join(b.thinking for b in m.content if isinstance(b, ThinkingContent))
            text = "".join(b.text for b in m.content if isinstance(b, TextContent))
            calls = [f"{b.name}({b.arguments})" for b in m.content if isinstance(b, ToolCallContent)]
            if thinking:
                parts.append(f"[thinking] {thinking}")
            if text:
                parts.append(text)
            if calls:
                parts.append("[tool calls] " + "; ".join(calls))
            lines.append(f"Assistant: {' '.join(parts)}")
        elif isinstance(m, ToolResult):
            content = "".join(b.text for b in m.content if isinstance(b, TextContent))
            lines.append(f"ToolResult({m.toolName}): {content}")
        elif isinstance(m, CompactionSummaryMessage):
            lines.append(f"Summary: {m.summary}")
    return "\n".join(lines)


async def summarize(
    messages: Sequence[Message],
    provider,
    model: ModelConfig,
) -> str:
    """用同一个模型把旧消息生成摘要。失败时抛 CompactionError。"""
    conversation = serialize_messages(messages)
    prompt = f"<conversation>\n{conversation}\n</conversation>\n\n{SUMMARIZATION_PROMPT}"

    context = ModelContext(
        model=model,
        system_prompt=SUMMARIZATION_SYSTEM_PROMPT,
        messages=[
            UserMessage(content=prompt, timestamp=datetime.now(UTC)),
        ],
    )

    assistant_message = None
    async for event in provider.stream(context):
        if isinstance(event, StreamFailed):
            raise CompactionError(f"summarization failed: {event.error}")
        if isinstance(event, StreamCompleted):
            assistant_message = event.message

    if assistant_message is None:
        raise CompactionError("summarization returned no message")

    return "".join(b.text for b in assistant_message.content if isinstance(b, TextContent)).strip()


async def compact_messages(
    messages: Sequence[Message],
    provider,
    model: ModelConfig,
    settings: CompactionSettings,
    force: bool = False,
) -> list[Message]:
    """上下文压缩总入口。

    未启用 / 未超阈值 / 无可压缩历史 / 摘要失败时，都安全返回原消息。
    force=True 时跳过 should_compact，用于手动 /compact。
    """
    if not settings.enabled:
        return list(messages)

    if not force and not should_compact(messages, model, settings):
        return list(messages)

    if force:
        # 手动压缩：只要有多个轮次，就保留最后一个轮次，压缩之前全部历史。
        user_indices = [i for i, m in enumerate(messages) if isinstance(m, UserMessage)]
        if len(user_indices) < 2:
            return list(messages)
        cut_index = user_indices[-1]
    else:
        cut_index = find_cut_index(messages, settings.keep_recent_turns)
        if cut_index == 0:
            return list(messages)

    history = messages[:cut_index]
    tail = messages[cut_index:]

    try:
        summary = await summarize(history, provider, model)
    except Exception:
        # 摘要失败绝不能丢对话，保持原样继续。
        return list(messages)

    summary_msg = CompactionSummaryMessage(
        summary=summary,
        timestamp=datetime.now(UTC),
        tokens_before=latest_prompt_tokens(messages) or 0,
    )

    return [summary_msg, *tail]
