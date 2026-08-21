"""tui_app.controller — 把 TUI 组件与 Coding 会话/命令桥接起来。"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from coding_agent.commands import CommandContext, CommandRegistry
from coding_agent.session import CodingSession


class TuiController:
    """TUI 应用层与 CodingSession / CommandRegistry 之间的桥。"""

    def __init__(
        self,
        *,
        session: CodingSession,
        registry: CommandRegistry,
        command_context: CommandContext,
        session_store: Any,
        workspace: Path,
        session_factory: Callable[..., CodingSession],
    ) -> None:
        self.session = session
        self.registry = registry
        self.command_context = command_context
        self.session_store = session_store
        self.workspace = workspace
        self._session_factory = session_factory
        self._handler = None
        self._agent_unsubscribe = None
        self._coding_unsubscribe = None

    def subscribe(self, handler) -> None:
        """订阅当前 Agent 与 Coding 事件；切换会话后自动重连。"""
        self._handler = handler
        self._resubscribe()

    def _resubscribe(self) -> None:
        if self._agent_unsubscribe is not None:
            self._agent_unsubscribe()
            self._agent_unsubscribe = None
        if self._coding_unsubscribe is not None:
            self._coding_unsubscribe()
            self._coding_unsubscribe = None
        if self._handler is not None:
            self._agent_unsubscribe = self.session.agent.subscribe(self._handler)
            self._coding_unsubscribe = self.session.subscribe(self._handler)

    async def run_prompt(self, text: str) -> str:
        """执行任务并持久化当前历史，保持与 CLI 相同的保存语义。"""
        try:
            return await self.session.prompt(text)
        finally:
            self.session.save()

    async def run_command(self, text: str):
        return await self.registry.execute(text, self.command_context)

    def resolve_approval(self, request_id: str, approved: bool) -> bool:
        """把用户的 y/n 决策交给 CodingSession 的审批钩子。"""
        return self.session.resolve_tool_approval(request_id, approved)

    async def load_session(self, session_id: str) -> None:
        meta, messages = self.session_store.load(session_id)
        self.session = self._session_factory(
            session_id=session_id,
            history=messages,
            created_at=meta.created_at,
        )
        self.command_context = CommandContext(
            session=self.session,
            session_store=self.session_store,
            workspace=self.workspace,
        )
        self._resubscribe()

    def delete_session(self, session_id: str) -> bool:
        self.session_store.delete(session_id)
        return True
