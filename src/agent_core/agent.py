"""agent_core.agent — 有状态 Agent：subscribe + processEvents。"""

import asyncio
import inspect
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from agent_core.compaction import CompactionSettings, compact_messages
from agent_core.events import AgentEvent, MessageCompleted, SteeringQueued
from agent_core.loop import BeforeToolCallHook, run_loop
from agent_core.types import AgentTool
from ai.types import (
    AssistantMessage,
    CompactionSummaryMessage,
    Message,
    ModelConfig,
    TextContent,
    ToolCallContent,
    ToolResult,
    UserMessage,
)

Listener = Any


class Agent:
    def __init__(
        self,
        *,
        provider,
        model,
        system_prompt: str | None = None,
        tools: Sequence[AgentTool] = (),
        max_turns: int = 20,
        history: Sequence[Message] = (),
        compaction_settings: CompactionSettings | None = None,
        before_tool_call_hook: BeforeToolCallHook | None = None,
    ):
        self._tools: Sequence[AgentTool] = tools
        self._provider = provider
        self._model = model
        self._system_prompt = system_prompt
        self._listeners: set = set()  # 对应 pi 的 listeners Set
        self.max_turns = max_turns
        self._cancel = asyncio.Event()
        self._messages = list(history)
        self._compaction_settings = compaction_settings or CompactionSettings()
        self.before_tool_call_hook = before_tool_call_hook

        # 插队机制，最多保留 10 条待处理消息。
        self._steering_queue: asyncio.Queue[UserMessage] = asyncio.Queue(maxsize=10)

    @property
    def model(self) -> ModelConfig:
        return self._model

    def set_model(self, model: ModelConfig) -> None:
        """更新后续模型调用与上下文压缩使用的模型。"""
        self._model = model

    def cancel(self) -> None:
        """请求取消活动轮次（03-contracts §4：CLI Ctrl+C -> CodingSession -> Agent）。"""

        self._cancel.set()

    def subscribe(self, listener):
        """
        注册监听器，返回退订函数
        """

        self._listeners.add(listener)

        # 闭包，记住内部监听器
        def unsubscribe():
            # self._listeners.remove(listener)
            self._listeners.discard(listener)  # 更加健壮，不存在的listener不会报错

        return unsubscribe

    async def _process_event(self, event: AgentEvent):
        """
        先按照类型更新状态，再顺序await所有监听器
        """

        if isinstance(event, MessageCompleted):
            self._messages.append(event.message)
        elif isinstance(event, SteeringQueued):
            self._messages.extend(event.messages)

        for listener in self._listeners:
            result = listener(event)
            if inspect.isawaitable(result):  # 监听器可为同步或异步（pi: void | Promise<void>）
                await result

    async def run(self, user_prompt: str):

        async def _compact_and_sync(messages: list[Message]):
            new_messages = await compact_messages(
                messages,
                self._provider,
                self._model,
                self._compaction_settings,
                force=False,
            )
            self._messages = list(new_messages)
            return new_messages

        self._cancel.clear()  # 新轮次清空上次取消信号（否则下一轮立即判 cancelled）
        try:
            return await run_loop(
                provider=self._provider,
                model=self._model,
                system_prompt=self._system_prompt,
                user_prompt=user_prompt,
                emit=self._process_event,
                tools=self._tools,
                history=self._messages,
                max_turns=self.max_turns,
                cancel=self._cancel,
                compactor=_compact_and_sync,
                before_tool_call_hook=self.before_tool_call_hook,
                drain_steering=self._drain_steering_message,
            )
        except asyncio.CancelledError:
            # 轮次在工具执行中被取消：历史末尾会留下"悬空"的 assistant 工具调用
            # （OpenAI 要求 tool 消息紧随 tool_calls，否则下一轮请求 400）。
            self._rollback_interrupted_tool_turn()
            raise

    async def compact_now(self):
        if not self._messages:
            return "当前上下文无需压缩"
        new_messages = await compact_messages(
            self._messages,
            self._provider,
            self._model,
            self._compaction_settings,
            force=True,
        )
        self._messages = list(new_messages)
        if isinstance(new_messages[0], CompactionSummaryMessage):
            return new_messages[0].summary
        return "当前上下文无需压缩"

    def _rollback_interrupted_tool_turn(self) -> None:
        """被取消轮次的未配对工具调用补上 "[cancelled by user]" 结果。

        OpenAI 要求 tool 消息紧随 assistant.tool_calls；直接删消息会让下一轮
        请求 400，且模型不知道发生了什么。为未得到结果的调用补一个取消结果，
        保留因果历史。
        """

        messages = self._messages
        index = len(messages) - 1
        paired: set[str] = set()
        while index >= 0 and isinstance(messages[index], ToolResult):
            result = messages[index]
            assert isinstance(result, ToolResult)  # 已由 while 条件保证
            paired.add(result.toolCallId)
            index -= 1

        assistant = messages[index] if index >= 0 else None
        if isinstance(assistant, AssistantMessage):
            calls = [b for b in assistant.content if isinstance(b, ToolCallContent)]
            for call in calls:
                if call.id not in paired:
                    messages.append(
                        ToolResult(
                            toolCallId=call.id,
                            toolName=call.name,
                            content=[TextContent(text="[cancelled by user]")],
                            details={"cancelled": True},
                            timestamp=datetime.now(UTC),
                            isError=False,  # 取消不是错误（04-boundaries 失败分类）
                        )
                    )

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def steer(self, content: str) -> bool:
        """将一条用户消息加入下一轮处理队列。"""
        content = content.strip()
        if not content:
            return False
        message = UserMessage(content=content, timestamp=datetime.now(UTC))
        try:
            self._steering_queue.put_nowait(message)
        except asyncio.QueueFull:
            return False
        return True

    def _drain_steering_message(self) -> list[UserMessage]:
        messages: list[UserMessage] = []
        while True:
            try:
                messages.append(self._steering_queue.get_nowait())
            except asyncio.QueueEmpty:
                return messages
