from collections.abc import Sequence

from ai.types import Message


def convert_to_llm(messages: Sequence[Message]) -> list[Message]:
    """把会话消息翻译成模型可读的 Message 列表（对应 pi 的 convertToLlm）。

    在 agent loop 的 LLM 调用边界调用一次：
    """
    converted: list[Message] = []
    for m in messages:
        if m.role == "user":
            converted.append(m)
    return converted
