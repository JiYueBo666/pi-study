"""coding_agent.provider — Provider 适配器组装。

把 ai.openai_model.stream 适配成 Agent 期望的 provider 协议。
CLI 和 TUI 共用这个适配器，避免各自重复实现。
"""

from ai.openai_model import stream as openai_stream
from ai.types import ModelConfig, ModelContext


class ProviderAdapter:
    """把 ai.openai_model.stream(client, model, ctx) 适配成 Agent 期望的 provider 协议。"""

    def __init__(self, client, model: ModelConfig) -> None:
        self._client = client
        self._model = model

    async def stream(self, context: ModelContext):
        async for event in openai_stream(self._client, self._model, context):
            yield event
