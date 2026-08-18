"""coding_agent.commands — UI 无关的命令系统。"""

from coding_agent.commands.base import (
    Command,
    CommandContext,
    CommandRegistry,
    CommandResult,
)
from coding_agent.commands.builtin import register_builtin_commands

__all__ = [
    "Command",
    "CommandContext",
    "CommandRegistry",
    "CommandResult",
    "register_builtin_commands",
]
