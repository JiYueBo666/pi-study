"""coding_agent.session — CodingSession：组装 Coding 产品。"""

from pathlib import Path

from agent_core.agent import Agent
from coding_agent.prompt import SYSTEM_PROMPT
from coding_agent.tools import build_tools
from coding_agent.workspace import WorkSpace as Workspace


class CodingSession:
    def __init__(self, *, provider, model, root: str | Path = ".", max_turns=30):
        self.workspace = Workspace(root=Path(root))
        self.agent = Agent(
            provider=provider,
            model=model,
            system_prompt=SYSTEM_PROMPT,  # ← ③ prompt.py
            tools=build_tools(self.workspace),  # ← ② tools.py 的组装函数
            max_turns=max_turns,
        )

    async def prompt(self, user_input: str) -> str:
        """把用户输入交给 Agent 执行一个完整轮次。"""
        return await self.agent.run(user_input)

    def cancel(self) -> None:
        """取消活动轮次（03-contracts §4：CLI Ctrl+C -> CodingSession -> Agent）。"""
        self.agent.cancel()

    @property
    def messages(self):
        return self.agent.messages
