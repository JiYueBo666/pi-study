"""agent_core.agent — 有状态 Agent：subscribe + processEvents。"""

import asyncio
import inspect
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from agent_core.events import AgentEvent, MessageCompleted
from agent_core.loop import run_loop
from agent_core.types import AgentTool
from ai.types import (
    AssistantMessage,
    Message,
    TextContent,
    ToolCallContent,
    ToolResult,
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
    ):
        self._tools: Sequence[AgentTool] = tools
        self._provider = provider
        self._model = model
        self._system_prompt = system_prompt
        self._listeners: set = set()  # 对应 pi 的 listeners Set
        self._messages: list[Message] = []  # 对应 pi 的 state.messages
        self.max_turns = max_turns
        self._cancel = asyncio.Event()

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

        for listener in self._listeners:
            result = listener(event)
            if inspect.isawaitable(result):  # 监听器可为同步或异步（pi: void | Promise<void>）
                await result

    async def run(self, user_prompt: str):
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
            )
        except asyncio.CancelledError:
            # 轮次在工具执行中被取消：历史末尾会留下"悬空"的 assistant 工具调用
            # （OpenAI 要求 tool 消息紧随 tool_calls，否则下一轮请求 400）。
            self._rollback_interrupted_tool_turn()
            raise

    def _rollback_interrupted_tool_turn(self) -> None:
        """被取消轮次的未配对工具调用补上 "[cancelled by user]" 结果。

        OpenAI 要求 tool 消息紧随 assistant.tool_calls；直接删消息会让下一轮
        请求 400，且模型不知道发生了什么。为未得到结果的调用补一个取消结果，
        保留因果历史。
        """

        messages = self._messages
        paired: set[str] = set()
        while messages and isinstance(messages[-1], ToolResult):
            last = messages.pop()
            assert isinstance(last, ToolResult)  # 已由 while 条件保证
            paired.add(last.toolCallId)
        if messages and isinstance(messages[-1], AssistantMessage):
            calls = [b for b in messages[-1].content if isinstance(b, ToolCallContent)]
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
