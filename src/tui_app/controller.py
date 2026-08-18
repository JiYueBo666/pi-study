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
        self._unsubscribe = None

    def subscribe(self, handler) -> None:
        """订阅当前 Agent 事件；切换会话后会自动重新订阅。"""
        self._handler = handler
        self._resubscribe()

    def _resubscribe(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
        if self._handler is not None:
            self._unsubscribe = self.session.agent.subscribe(self._handler)

    async def run_prompt(self, text: str) -> str:
        """执行任务并持久化当前历史，保持与 CLI 相同的保存语义。"""
        try:
            return await self.session.prompt(text)
        finally:
            self.session.save()

    async def run_command(self, text: str):
        return await self.registry.execute(text, self.command_context)

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
