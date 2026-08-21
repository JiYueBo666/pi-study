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
    ContextCompacted,
    MessageCompleted,
    MessageDelta,
    MessageStarted,
    ThinkingDeltaEvent,
    ToolCompleted,
    ToolStarted,
    ToolUpdated,
    TurnEnded,
    TurnStarted,
)
from agent_core.types import AgentTool, ToolExecutionResult
from ai.types import (
    AssistantMessage,
    CompactionSummaryMessage,
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

# 工具执行前钩子：None 表示继续执行，结果对象表示跳过执行并使用该结果。
BeforeToolCallHook = Callable[
    [AgentTool, ToolCallContent],
    Awaitable[ToolExecutionResult | None],
]


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
    compactor: Callable[[list[Message]], Awaitable[list[Message]]] | None = None,
    before_tool_call_hook: BeforeToolCallHook | None = None,
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
            tool_definitions = [_tool_definition(tool) for tool in tools]

            # 调用模型前，先预先处理上下文
            if compactor is not None:
                new_messages = await compactor(messages)

                # 为什么new_message[0]是compaction summary message类型？
                if len(new_messages) != len(messages) and isinstance(
                    new_messages[0], CompactionSummaryMessage
                ):
                    await emit(
                        ContextCompacted(
                            summary=new_messages[0].summary,
                            retained_count=len(new_messages) - 1,
                        )
                    )
                messages = new_messages

            # 模型调用：组上下文， 消费
            context = ModelContext(
                model=model,
                system_prompt=system_prompt,
                messages=messages,
                tools=tool_definitions,
            )
            assistant_message: AssistantMessage | None = None
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
                    await emit(
                        ThinkingDeltaEvent(delta=event.delta, partial=event.partial)
                    )
                elif isinstance(event, StreamCompleted):
                    assistant_message = event.message

            if assistant_message is None:
                await emit(AgentEnded("internal_error"))
                return "模型调用未返回完整消息"

            await emit(MessageCompleted(assistant_message))

            messages.append(assistant_message)
            calls = [
                b for b in assistant_message.content if isinstance(b, ToolCallContent)
            ]

            if not calls:
                await emit(TurnEnded(turn))
                await emit(AgentEnded("completed"))
                return "".join(
                    b.text
                    for b in assistant_message.content
                    if isinstance(b, TextContent)
                )
            for call in calls:
                tool = tool_by_name.get(call.name)

                # 没找到工具，返回执行结果。
                if tool is None:
                    exec_result = ToolExecutionResult(
                        content=f"未知工具:{call.name}", is_error=True
                    )
                # 找到工具，先让业务层有机会放行或覆盖执行结果。
                else:
                    override_result: ToolExecutionResult | None = None
                    if before_tool_call_hook is not None:
                        override_result = await before_tool_call_hook(tool, call)

                    if override_result is None:
                        await emit(ToolStarted(call))
                        exec_result = await _execute_tool_with_progress(
                            tool,
                            call,
                            cancel or asyncio.Event(),
                            emit,
                        )
                    else:
                        exec_result = override_result
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


async def _execute_tool_with_progress(
    tool: AgentTool,
    call: ToolCallContent,
    cancel: asyncio.Event,
    emit: EventSink,
) -> ToolExecutionResult:
    """执行单个工具并转发进度事件。

    对应 pi 的 executePreparedToolCall（agent-loop.ts）：进度回调不逐个 await，
    先收集成 Task 列表，工具结束后一次性批量等待（acceptingUpdates 闸门）。
    """

    accepting_updates = True
    update_tasks: list[asyncio.Task] = []

    def on_progress(line: str) -> None:
        nonlocal accepting_updates
        if accepting_updates:

            async def _emit_update(_line: str = line) -> None:
                await emit(ToolUpdated(call=call, partial=_line))

            update_tasks.append(asyncio.create_task(_emit_update()))

    try:
        exec_result = await tool.execute(call, cancel, on_progress=on_progress)
    finally:
        # 无论工具成功/失败/被取消，都关闭进度闸门并等待已排队的更新事件，
        # 避免 asyncio.Task 泄漏或事件顺序错乱。
        accepting_updates = False
        if update_tasks:
            await asyncio.gather(*update_tasks)
    return exec_result


def _tool_definition(tool: AgentTool) -> ToolDefinition:
    """将工具的 Pydantic 模型或旧 JSON Schema 转换为模型定义。

    ``args_model`` 是逐步迁移到 Pydantic 时新增的约定；没有它的第三方或
    测试工具仍可继续提供 ``parameters`` 字典。
    """

    args_model = getattr(tool, "args_model", None)
    if args_model is not None:
        return ToolDefinition.from_model(
            name=tool.name,
            description=tool.description,
            parameter_model=args_model,
        )

    parameters = getattr(tool, "parameters", {})
    return ToolDefinition(
        name=tool.name,
        description=tool.description,
        parameters=parameters,
    )
