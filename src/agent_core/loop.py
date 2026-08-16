"""agent_core.loop — Agent 主循环。

占位实现：按 docs/design/06-delivery-plan.md，真正的模型 -> 工具 -> 模型
循环在 Phase 3 实现。当前仅提供 CLI 可导入的最小 run_agent。
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from agent_core.events import (
    AgentEnded,
    AgentEvent,
    AgentStarted,
    MessageCompleted,
    MessageDelta,
    MessageStarted,
    ThinkingDeltaEvent,
    ToolCompleted,
    ToolStarted,
    TurnEnded,
    TurnStarted,
)
from agent_core.types import AgentTool, ToolExecutionResult
from ai.types import (
    Message,
    ModelConfig,
    ModelContext,
    StreamCompleted,
    StreamFailed,
    TextContent,
    TextDelta,
    ThinkingDelta,
    ToolCallContent,
    ToolDefinition,
    ToolResult,
    UserMessage,
)

# 事件接收器：对应 pi 的 AgentEventSink（agent-loop.ts:47）
EventSink = Callable[[AgentEvent], Awaitable[None]]


async def run_loop(
    *,
    provider: Any,
    model: ModelConfig,
    system_prompt: str | None,
    user_prompt: str,
    emit: EventSink,
    tools: Sequence[AgentTool] = (),
    max_turns: int = 20,
    cancel: asyncio.Event | None = None,
    history: Sequence[Message] | None,
):
    # Trace开始
    await emit(AgentStarted())

    # 用户消息进入历史，发送消息事件
    user = UserMessage(content=user_prompt, timestamp=datetime.now(UTC))
    messages: list[Message] = [*history, user] if history else [user]
    tool_by_name = {t.name: t for t in tools}
    await emit(MessageStarted(user))
    await emit(MessageCompleted(user))

    # 进入turn开启对话
    try:
        for turn in range(1, max_turns + 1):
            # 协作式取消：外部设置了 cancel 信号（CLI Ctrl+C）
            if cancel is not None and cancel.is_set():
                await emit(AgentEnded("cancelled"))
                return "[cancelled]"

            await emit(TurnStarted(turn))

            # 协议转换。
            tool_definitions = [
                ToolDefinition(name=t.name, description=t.description, parameters=t.parameters) for t in tools
            ]

            # 模型调用：组上下文， 消费
            context = ModelContext(
                model=model,
                system_prompt=system_prompt,
                messages=messages,
                tools=tool_definitions,
            )
            assistant_message: Message
            # ai回复，空标记
            await emit(MessageStarted())

            # 开启模型调用，消费异步流
            async for event in provider.stream(context):
                if isinstance(event, StreamFailed):
                    await emit(AgentEnded("model_failed"))
                    return f"模型调用失败: {event.error}"
                elif isinstance(event, TextDelta):
                    # 转发为 L1 事件：MessageDelta 带 delta + 累积快照
                    await emit(MessageDelta(delta=event.delta, partial=event.partial))
                elif isinstance(event, ThinkingDelta):
                    await emit(ThinkingDeltaEvent(delta=event.delta, partial=event.partial))
                elif isinstance(event, StreamCompleted):
                    assistant_message = event.message

            await emit(MessageCompleted(assistant_message))

            messages.append(assistant_message)
            calls = [b for b in assistant_message.content if isinstance(b, ToolCallContent)]

            if not calls:
                await emit(TurnEnded(turn))
                await emit(AgentEnded("completed"))
                return "".join(b.text for b in assistant_message.content if isinstance(b, TextContent))
            for call in calls:
                await emit(ToolStarted(call))
                tool = tool_by_name.get(call.name)
                if tool is None:
                    exec_result = ToolExecutionResult(content=f"未知工具:{call.name}", is_error=True)
                else:
                    exec_result = await tool.execute(call, cancel or asyncio.Event())
                # 结果转成 ToolResult 消息（ai.types 里已有，role="toolResult"）
                result_msg = ToolResult(
                    toolCallId=call.id,
                    toolName=call.name,
                    content=[TextContent(text=exec_result.content)],
                    details=exec_result.details,
                    timestamp=datetime.now(UTC),
                    isError=exec_result.is_error,
                )

                messages.append(result_msg)
                await emit(MessageCompleted(result_msg))
                await emit(ToolCompleted(call, result_msg))
            await emit(TurnEnded(turn))
    except asyncio.CancelledError:
        # 任务级取消（CLI task.cancel）：发出终态事件后重新抛出，回到 idle
        await emit(AgentEnded("cancelled"))
        raise
    await emit(AgentEnded("max_turns"))
    return f"达到max turn轮数: {max_turns} 轮"
