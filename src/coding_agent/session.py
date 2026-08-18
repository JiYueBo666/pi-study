"""coding_agent.session — CodingSession：组装 Coding 产品。"""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agent_core.agent import Agent
from agent_core.compaction import CompactionSettings
from agent_core.session.jsonl import JsonlSessionStore
from agent_core.session.types import SessionMeta, SessionStore
from coding_agent.prompt import SYSTEM_PROMPT
from coding_agent.tools import build_tools
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
        self.session_id = session_id
        self.workspace = Workspace(root=Path(root))
        self._created_at = created_at or datetime.now(UTC)
        self.max_turns = max_turns

        self.session_store = session_store or JsonlSessionStore(
            sessions_dir=Path(self.workspace.root) / ".pi-study" / "sessions"
        )
        self.compaction_settings = compaction_settings or CompactionSettings()

        self.agent = Agent(
            provider=provider,
            model=model,
            system_prompt=SYSTEM_PROMPT,  # ← ③ prompt.py
            tools=build_tools(self.workspace),  # ← ② tools.py 的组装函数
            max_turns=self.max_turns,
            history=history,
            compaction_settings=self.compaction_settings,
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


def new_session_id() -> str:
    return f"sess_{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:4]}"
