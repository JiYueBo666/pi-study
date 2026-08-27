"""agent_core.loop — 由模型工具调用驱动的 Agent 主循环。"""

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
    SteeringQueued,
    ThinkingDeltaEvent,
    ToolCompleted,
    ToolDisplayResult,
    ToolStarted,
    ToolUpdated,
    TurnEnded,
    TurnStarted,
)
from agent_core.types import AgentTool, ToolExecutionResult, ToolOutput
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

DrainSteering = Callable[[], Sequence[UserMessage]]


async def run_loop(
    *,
    provider: Any,
    model: ModelConfig,
    system_prompt: str | None,
    user_prompt: str,
    emit: EventSink,
    tools: Sequence[AgentTool] = (),
    max_turns: int | None = None,
    cancel: asyncio.Event | None = None,
    history: Sequence[Message] | None,
    compactor: Callable[[list[Message]], Awaitable[list[Message]]] | None = None,
    before_tool_call_hook: BeforeToolCallHook | None = None,
    drain_steering: DrainSteering | None = None,
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
        turn = 0
        while True:
            turn += 1
            # 轮数只作为可选的安全熔断，不是正常完成条件。正常情况下
            # 由模型是否继续返回工具调用决定是否进入下一轮。
            if max_turns is not None and turn > max_turns:
                await emit(AgentEnded("max_turns"))
                return f"达到max turn轮数: {max_turns} 轮"
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
                if len(new_messages) != len(messages) and isinstance(new_messages[0], CompactionSummaryMessage):
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
                    await emit(AgentEnded("model_failed", error=event.error))
                    return f"模型调用失败: {event.error}"
                elif isinstance(event, TextDelta):
                    # 转发为 L1 事件：MessageDelta 带 delta + 累积快照
                    await emit(MessageDelta(delta=event.delta, partial=event.partial))
                elif isinstance(event, ThinkingDelta):
                    await emit(ThinkingDeltaEvent(delta=event.delta, partial=event.partial))
                elif isinstance(event, StreamCompleted):
                    assistant_message = event.message

            if assistant_message is None:
                error = "模型流结束，但没有返回 StreamCompleted 消息"
                await emit(AgentEnded("internal_error", error=error))
                return "模型调用未返回完整消息"

            await emit(MessageCompleted(assistant_message))

            messages.append(assistant_message)

            # 工具调用处理阶段
            calls = [b for b in assistant_message.content if isinstance(b, ToolCallContent)]

            if not calls:
                steering = drain_steering() if drain_steering is not None else ()

                if steering:
                    messages.extend(steering)
                    await emit(SteeringQueued(turn=turn, messages=tuple(steering)))
                    await emit(TurnEnded(turn))
                    continue

                await emit(TurnEnded(turn))
                await emit(AgentEnded("completed"))

                return "".join(b.text for b in assistant_message.content if isinstance(b, TextContent))
            for call in calls:
                tool = tool_by_name.get(call.name)

                # 没找到工具，返回执行结果。
                if tool is None:
                    exec_result = ToolExecutionResult(output=ToolOutput(f"未知工具:{call.name}"), is_error=True)
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
                context_output = exec_result.effective_context_output
                display_output = exec_result.effective_display_output

                result_msg = ToolResult(
                    toolCallId=call.id,
                    toolName=call.name,
                    content=[TextContent(text=context_output.text)],
                    details=exec_result.details,
                    timestamp=datetime.now(UTC),
                    isError=exec_result.is_error,
                )
                messages.append(result_msg)
                await emit(MessageCompleted(result_msg))
                await emit(
                    ToolCompleted(
                        call=call,
                        result=result_msg,
                        display=ToolDisplayResult(
                            tool_name=call.name,
                            output=display_output,
                            details=exec_result.details,
                            is_error=exec_result.is_error,
                        ),
                    )
                )

            steering = drain_steering() if drain_steering is not None else ()
            if steering:
                messages.extend(steering)
                await emit(SteeringQueued(turn=turn, messages=tuple(steering)))
            await emit(TurnEnded(turn))
            continue
    except asyncio.CancelledError:
        # 任务级取消（CLI task.cancel）：发出终态事件后重新抛出，回到 idle
        await emit(AgentEnded("cancelled"))
        raise


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
