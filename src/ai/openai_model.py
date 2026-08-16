import json
import os
from datetime import UTC, datetime
from typing import Any, cast

from openai import AsyncOpenAI

from ai.stream import AssistantMessageBuilder
from ai.types import (
    AssistantMessage,
    ModelConfig,
    ModelContext,
    StreamCompleted,
    StreamFailed,
    StreamStarted,
    TextContent,
    TextDelta,
    ThinkingDelta,
    ToolCallContent,
    ToolCallDelta,
    ToolResult,
    UserMessage,
)

"""
仅仅产出流事件
TextDelta 和 ToolCallDelta 以及StreamCompleted 
"""


def _delta_extra(delta) -> dict:
    """SDK 未声明但供应商实际返回的 delta 字段（如 reasoning_content）。"""

    return getattr(delta, "__pydantic_extra__", None) or {}


def _message_params(context: ModelContext):
    """
    供应商无关消息 --> openai 的 message 列表。

    OpenAI Chat Completions 多轮工具调用格式要求：
    - assistant 消息必须同时带 text 与 tool_calls 块（有工具调用时）；
    - 每个 ToolResult 必须是独立 role="tool" 消息并带 tool_call_id 引用。
    """

    params: list[dict] = []
    if context.system_prompt:
        params.append({"role": "system", "content": context.system_prompt})
    for m in context.messages:
        if isinstance(m, UserMessage):
            params.append({"role": "user", "content": m.content})
        elif isinstance(m, ToolResult):
            # 工具结果：必须通过 tool_call_id 匹配此前的调用（03-contracts §1）
            params.append(
                {
                    "role": "tool",
                    "content": m.content[0].text if m.content else "",
                    "tool_call_id": m.toolCallId,
                }
            )
        elif isinstance(m, AssistantMessage):
            text = "".join(b.text for b in m.content if isinstance(b, TextContent))
            tool_calls = [
                {
                    "id": b.id,
                    "type": "function",
                    "function": {"name": b.name, "arguments": json.dumps(b.arguments)},
                }
                for b in m.content
                if isinstance(b, ToolCallContent)
            ]
            if text or tool_calls:
                if tool_calls:
                    params.append(
                        {
                            "role": "assistant",
                            "content": text or None,
                            "tool_calls": tool_calls,
                        }
                    )
                else:
                    params.append({"role": "assistant", "content": text})
    return params


def _stop_reason(finish_reason: str | None):
    mapping = {"stop": "stop", "length": "length", "tool_calls": "toolUse"}
    return mapping.get(finish_reason or "", "stop")


def from_env() -> tuple[AsyncOpenAI, ModelConfig]:
    api_key = os.getenv("OPENAI_API_KEY")  # 缺就 raise RuntimeError（原类里的逻辑）
    model_id = os.getenv("OPENAI_MODEL")
    base_url = os.getenv("OPENAI_BASE_URL")

    if not api_key:
        raise RuntimeError("OPENAI KEY NOT SET")
    if not model_id:
        raise RuntimeError("MODEL ID NOT SET")
    if not base_url:
        raise RuntimeError("BASE URL NOT SET")
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return client, ModelConfig(id=model_id)


def _tool_definitions(context: ModelContext) -> list[dict]:
    """ToolDefinition -> OpenAI tools 参数（function calling）。"""

    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in context.tools
    ]


async def stream(client: AsyncOpenAI, model: ModelConfig, context: ModelContext):
    """
    转换成openai适用格式
    """
    messages = _message_params(context)
    tools = _tool_definitions(context)
    try:
        kwargs: dict[str, Any] = {
            "model": model.id,
            "messages": cast(Any, messages),
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools  # 关键：把工具定义发给模型
        sdk_stream = await client.chat.completions.create(**kwargs)
    except Exception as exc:
        yield StreamFailed(error=f"{type(exc).__name__}: {exc}")

        return
    builder = AssistantMessageBuilder(
        model=model.id,
        provider=model.provider,
        api=model.api,
        timestamp=datetime.now(UTC),
    )
    yield StreamStarted()
    finish_reason = None
    try:
        async for chunk in sdk_stream:
            for choice in chunk.choices:
                # DeepSeek 等兼容接口在 delta 的扩展字段里流式返回 reasoning_content：
                # 思考期可能长达数十秒，不处理则 CLI 表现为"死寂"。
                reasoning = _delta_extra(choice.delta).get("reasoning_content")
                if reasoning:
                    builder.add_thinking(reasoning)
                    yield ThinkingDelta(delta=reasoning, partial=builder.get_thinking)

                if choice.delta.content:
                    builder.add_text(choice.delta.content)
                    yield TextDelta(delta=choice.delta.content, partial="".join(builder.get_parts))

                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                for tool_call in choice.delta.tool_calls or []:
                    fn = tool_call.function
                    builder.add_tool_call(
                        tool_call.index,
                        tool_call.id,
                        fn.name if fn else None,
                        fn.arguments if fn else "",
                    )
                    yield ToolCallDelta(
                        index=tool_call.index,
                        id=tool_call.id,
                        name=fn.name if fn else None,
                        arguments_delta=fn.arguments if fn else "",
                    )
    except Exception as exc:  # 流中断（网络等）-> StreamFailed，不外抛（03-contracts 失败分类）
        await _close_quietly(sdk_stream)
        yield StreamFailed(error=f"{type(exc).__name__}: {exc}")
        return
    await _close_quietly(sdk_stream)
    yield StreamCompleted(message=builder.build(stop_reason=_stop_reason(finish_reason), usage={}))


async def _close_quietly(sdk_stream) -> None:
    """显式关闭 SDK 流并吞掉 httpcore2 的关闭噪音（generator didn't stop）。"""

    try:
        await sdk_stream.close()
    except Exception:
        pass
