"""coding_agent.session — CodingSession：组装 Coding 产品。"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_core.agent import Agent
from agent_core.compaction import CompactionSettings, input_token_limit, latest_prompt_tokens
from agent_core.session.jsonl import JsonlSessionStore
from agent_core.session.types import SessionMeta, SessionStore
from agent_core.types import AgentTool, ToolExecutionResult, ToolOutput
from ai.types import ModelConfig, ToolCallContent
from coding_agent.event import (
    CodingEvent,
    ToolApprovalCompleted,
    ToolApprovalRequest,
    ToolApprovalRequested,
    ToolApprovalResult,
)
from coding_agent.prompt import SYSTEM_PROMPT
from coding_agent.tools_pacakge.tool_config import (
    ApprovalMode,
    RejectResponse,
    load_reject_prompt_map,
)
from coding_agent.tools_pacakge.tools import build_tools
from coding_agent.workspace import WorkSpace as Workspace

type CodingEventListener = Callable[[CodingEvent], Awaitable[None] | None]


class CodingSession:
    def __init__(
        self,
        *,
        provider,
        model,
        root: str | Path = ".",
        max_turns: int | None = None,
        session_id: str | None = None,
        history=(),
        session_store: SessionStore | None = None,
        created_at: datetime | None = None,
        compaction_settings: CompactionSettings | None = None,
    ):
        # ------------------会话ID
        self.session_id = session_id
        self.workspace = Workspace(root=Path(root))
        self._created_at = created_at or datetime.now(UTC)
        self.session_store = session_store or JsonlSessionStore(
            sessions_dir=Path(self.workspace.root) / ".pi-study" / "sessions"
        )
        # ------------------Agent参数配置
        self.max_turns = max_turns
        self.compaction_settings = compaction_settings or CompactionSettings()
        # ------------------工具集合
        self.tools = build_tools(self.workspace)
        # ------------------审批模式，工具调用配置
        self.approval_mode = ApprovalMode.ASK
        self.reject_response = RejectResponse.CONTINUE
        self.reject_prompt_map = load_reject_prompt_map()
        self._before_tool_call = self.tool_approval_hook  # 前处理钩子
        self._pending_approvals: dict[
            str,
            asyncio.Future[ToolApprovalResult],
        ] = {}
        # 监听器
        self._listeners: set[CodingEventListener] = set()

        self.agent = Agent(
            provider=provider,
            model=model,
            system_prompt=SYSTEM_PROMPT,  # ← ③ prompt.py
            tools=self.tools,  # ← ② tools.py 的组装函数
            max_turns=self.max_turns,
            history=history,
            compaction_settings=self.compaction_settings,
            before_tool_call_hook=self._before_tool_call,
        )

    def subscribe(self, listener: CodingEventListener) -> Callable[[], None]:
        """订阅 Coding 业务事件，并返回退订函数。"""
        self._listeners.add(listener)

        def unsubscribe() -> None:
            self._listeners.discard(listener)

        return unsubscribe

    async def _emit(self, event: CodingEvent) -> None:
        """逐个派发业务事件，兼容同步和异步监听器。"""
        for listener in tuple(self._listeners):
            result = listener(event)
            if inspect.isawaitable(result):
                await result

    async def prompt(self, user_input: str) -> str:
        """把用户输入交给 Agent 执行一个完整轮次。"""
        return await self.agent.run(user_input)

    async def compact(self) -> str:
        """手动压缩当前会话上下文，并持久化压缩结果。"""
        result = await self.agent.compact_now()
        self.save()
        return result

    def cancel(self) -> None:
        """取消活动轮次（03-contracts §4：CLI Ctrl+C -> CodingSession -> Agent）。"""
        self.agent.cancel()

        for future in self._pending_approvals.values():
            if not future.done():
                future.cancel()

    @property
    def messages(self):
        return self.agent.messages

    def steer(self, content: str) -> bool:
        """将运行中的用户消息转发给 Agent 的下一轮队列。"""
        return self.agent.steer(content)

    @property
    def model(self) -> ModelConfig:
        return self.agent.model

    def set_model(self, model_id: str) -> ModelConfig:
        """切换后续调用使用的模型，同时保留当前 provider 与 API 类型。"""
        model_id = model_id.strip()
        if not model_id:
            raise ValueError("模型 ID 不能为空")

        current = self.model
        model = ModelConfig(
            id=model_id,
            provider=current.provider,
            api=current.api,
            context_window=current.context_window,
            max_output_tokens=current.max_output_tokens,
        )
        self.agent.set_model(model)
        return model

    def status(self) -> dict:
        """返回与 UI 无关的会话和上下文统计。"""
        messages = self.messages
        role_counts: dict[str, int] = {}
        for message in messages:
            role_counts[message.role] = role_counts.get(message.role, 0) + 1

        context_tokens = latest_prompt_tokens(messages)
        threshold = input_token_limit(self.model, self.compaction_settings)
        return {
            "session_id": self.session_id,
            "workspace": str(self.workspace.root),
            "model": self.model.id,
            "message_count": len(messages),
            "role_counts": role_counts,
            "context_tokens": context_tokens,
            "compaction_threshold": threshold,
            "compaction_enabled": self.compaction_settings.enabled,
            "pending_approvals": len(self._pending_approvals),
            "approval_mode": self.approval_mode.value,
        }

    def save(
        self,
    ):
        messages = self.messages

        if self.session_id is None:
            self.session_id = new_session_id()
        meta = SessionMeta(
            id=self.session_id,
            cwd=str(self.workspace.root),
            created_at=self._created_at,
            updated_at=datetime.now(UTC),
            max_turns=self.max_turns,
            message_count=len(self.messages),
        )

        self.session_store.save(meta, messages)

    async def tool_approval_hook(
        self,
        tool: AgentTool,
        call: ToolCallContent,
    ) -> ToolExecutionResult | None:
        tool_use = next(t for t in self.tools if t.name == tool.name)
        if tool_use.is_safe:
            return None
        if self.approval_mode is ApprovalMode.AutoAccept:
            return None
        approved, intent = await self.request_approval(tool, call)

        if approved:
            return None
        return ToolExecutionResult(
            output=ToolOutput(intent),
            details={"approval_required": True, "approved": False},
            is_error=True,
        )

    async def request_approval(
        self,
        tool: AgentTool,
        call: ToolCallContent,
    ) -> ToolApprovalResult:
        # 创建请求ID，Future并登记
        request_id = uuid4().hex

        request = ToolApprovalRequest(
            request_id=request_id,
            tool_name=tool.name,
            tool_description=tool.description,
            call=call,
        )

        future: asyncio.Future[ToolApprovalResult] = asyncio.get_running_loop().create_future()
        self._pending_approvals[request_id] = future

        try:
            await self._emit(ToolApprovalRequested(request=request))
            result = await future

            await self._emit(ToolApprovalCompleted(call=call, approved=result[0]))
            return result
        finally:
            self._pending_approvals.pop(request.request_id, None)

    def resolve_tool_approval(self, request_id: str, approved: bool) -> bool:
        future = self._pending_approvals.get(request_id)

        if future is None or future.done():
            return False

        if approved:
            result = (True, "user_approved")
        else:
            prompt = self.reject_prompt_map[self.reject_response.value]
            result = (False, prompt)

        future.set_result(result)
        return True


def new_session_id() -> str:
    return f"sess_{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:4]}"
