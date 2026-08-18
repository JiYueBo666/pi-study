"""mypi 入口 — 启动 TUI。"""

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from agent_core.session.jsonl import JsonlSessionStore
from ai.openai_model import from_env
from coding_agent.commands import (
    CommandContext,
    CommandRegistry,
    register_builtin_commands,
)
from coding_agent.provider import ProviderAdapter
from coding_agent.session import CodingSession
from tui_app.app import MyPiApp
from tui_app.controller import TuiController


def main() -> None:
    """mypi 启动入口。"""

    parser = argparse.ArgumentParser(description="pi-study TUI")
    parser.add_argument("--workspace", default=".", help="工作区根目录（默认当前目录）")
    args = parser.parse_args()

    load_dotenv()
    client, model = from_env()
    workspace = Path(args.workspace).resolve()
    store = JsonlSessionStore(workspace / ".pi-study" / "sessions")

    def make_session(
        session_id: str | None = None,
        history=(),
        created_at=None,
    ) -> CodingSession:
        return CodingSession(
            provider=ProviderAdapter(client, model),
            model=model,
            root=workspace,
            session_id=session_id,
            history=history,
            created_at=created_at,
        )

    session = make_session()

    registry = CommandRegistry()
    register_builtin_commands(registry)
    command_context = CommandContext(session=session, session_store=store, workspace=workspace)
    controller = TuiController(
        session=session,
        registry=registry,
        command_context=command_context,
        session_store=store,
        workspace=workspace,
        session_factory=make_session,
    )

    app = MyPiApp(controller=controller)
    try:
        app.run()
    finally:
        asyncio.run(client.close())
