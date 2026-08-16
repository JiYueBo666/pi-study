"""ai.stream — 把流 delta 聚合为完整 AssistantMessage。

不变量（docs/design/03-contracts.md §1）：只有聚合完成的消息才可加入历史；
局部文本不是持久 AssistantMessage。

对应 pi 的 AssistantMessageEventStream：终结事件（done）既是流的终结，
又是最终结果（完整 AssistantMessage）的来源。阶段 1 只聚合文本；
工具调用解析在阶段 2 加入。
"""

import json
from datetime import datetime

from ai.types import (
    Api,
    AssistantMessage,
    ProviderID,
    TextContent,
    ThinkingContent,
    ToolCallContent,
)


class AssistantMessageBuilder:
    """
    负责字段解析，将Delta片段组装，返回AssistantMessage。
    """

    def __init__(self, *, model: str, provider: ProviderID, api: Api, timestamp: datetime):
        # 累积状态：文本片段列表
        self._model = model
        self._provider = provider
        self._api = api
        self._timestamp = timestamp
        self._text_parts: list[str] = []
        self._text_parts_str = ""
        self._thinking_parts: list[str] = []
        self._thinking_str = ""
        self._tool_calls: dict[int, dict] = {}

    def add_text(self, delta: str) -> None:
        # 空字符串直接忽略；否则累积进文本片段列表
        if delta:
            self._text_parts.append(delta)
            self._text_parts_str += delta

    def add_thinking(self, delta: str) -> None:
        """累积模型思考内容（reasoning）片段。"""

        if delta:
            self._thinking_parts.append(delta)
            self._thinking_str += delta

    def add_tool_call(self, index: int, id: str | None, name: str | None, arguments_delta: str):
        """
        累计一次工具调用的流式片段, id/name只在首个片段中出现
        """
        call = self._tool_calls.get(index)
        if call is None:
            self._tool_calls[index] = {
                "id": id or "",
                "name": name or "",
                "arguments": arguments_delta,
            }
        else:
            if id:
                call["id"] = id
            if name:
                call["name"] = name
            if arguments_delta:
                call["arguments"] += arguments_delta

    def build(self, *, stop_reason: str, usage: dict) -> AssistantMessage:
        # 思考块在最前，文本块次之，工具调用块最后
        content: list[TextContent | ThinkingContent | ToolCallContent] = []
        if self._thinking_parts:
            content.append(ThinkingContent(thinking="".join(self._thinking_parts)))
        if self._text_parts:
            content.append(TextContent(text="".join(self._text_parts)))

        for index in sorted(self._tool_calls):  # 按照index调用
            call = self._tool_calls[index]
            arguments: dict = {}
            try:
                parsed = json.loads(call["arguments"])
                arguments = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                arguments = {}  # 畸形参数 -> 空 dict（阶段 2 先宽容，阶段 4 再收紧）
            content.append(ToolCallContent(id=call["id"], name=call["name"], arguments=arguments))

        # 返回 AssistantMessage（content / timestamp / api / provider / model / usage / stopReason）
        # usage 传进来的 dict 直接用（现在是占位类型）
        return AssistantMessage(
            content=content,
            timestamp=self._timestamp,
            api=self._api,
            provider=self._provider,
            model=self._model,
            usage=usage,
            stopReason=stop_reason,
        )

    @property
    def get_parts(self):
        return self._text_parts_str

    @property
    def get_thinking(self):
        return self._thinking_str
