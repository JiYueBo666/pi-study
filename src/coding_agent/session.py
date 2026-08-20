"""coding_agent.session — CodingSession：组装 Coding 产品。"""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_core.agent import Agent
from agent_core.compaction import CompactionSettings
from agent_core.session.jsonl import JsonlSessionStore
from agent_core.session.types import SessionMeta, SessionStore
from agent_core.types import ToolApprovalRequest, ToolApprovalResult
from coding_agent.prompt import SYSTEM_PROMPT
from coding_agent.tools_pacakge.tool_config import (
    ApprovalMode,
    RejectResponse,
    load_reject_prompt_map,
)
from coding_agent.tools_pacakge.tools import build_tools
from coding_agent.workspace import WorkSpace as Workspace


class CodingSession:
    def __init__(
        self,
        *,
        provider,
        model,
        root: str | Path = ".",
        max_turns=30,
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

        self.agent = Agent(
            provider=provider,
            model=model,
            system_prompt=SYSTEM_PROMPT,  # ← ③ prompt.py
            tools=self.tools,  # ← ② tools.py 的组装函数
            max_turns=self.max_turns,
            history=history,
            compaction_settings=self.compaction_settings,
            beforeToolcallHook=self._before_tool_call,
        )

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
        request: ToolApprovalRequest,
    ) -> ToolApprovalResult:
        tool = next(t for t in self.tools if t.name == request.tool_name)
        if tool.is_safe:
            return True, "safe"

        if self.approval_mode is ApprovalMode.AutoAccept:
            return True, "auto_accept"
        future: asyncio.Future[ToolApprovalResult] = asyncio.get_running_loop().create_future()
        self._pending_approvals[request.request_id] = future

        try:
            return await future
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
