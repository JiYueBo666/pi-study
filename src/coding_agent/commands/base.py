"""命令系统 — UI 无关的命令解析与分发。

命令系统不依赖终端：不 print、不 input。UI 层（CLI / 未来 TUI）只负责
调用 `CommandRegistry.execute()` 并按 `CommandResult` 决定如何展示和退出。
"""

import shlex
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CommandResult:
    """命令执行结果，由 UI 层决定如何渲染。"""

    message: str | None = None
    should_exit: bool = False
    status: str = "ok"
    data: Any = None


@dataclass(frozen=True, slots=True)
class CommandContext:
    """命令执行时可访问的上下文。"""

    session: Any
    session_store: Any = None
    workspace: Path | None = None


@dataclass(frozen=True, slots=True)
class Command:
    """一条命令的定义。"""

    name: str
    description: str
    handler: Callable[[CommandContext, list[str]], Awaitable[CommandResult]]
    aliases: tuple[str, ...] = ()
    usage: str = ""


class CommandRegistry:
    """注册命令并按 `/name args...` 分发。"""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, command: Command) -> None:
        self._commands[command.name] = command
        for alias in command.aliases:
            self._commands[alias] = command

    async def execute(self, line: str, context: CommandContext) -> CommandResult:
        parts = shlex.split(line)
        if not parts or not parts[0].startswith("/"):
            return CommandResult(message="not a command", status="error")

        raw = parts[0][1:]
        command = self._commands.get(raw)
        if command is None:
            return CommandResult(
                message=f"unknown command: /{raw}",
                status="error",
            )

        return await command.handler(context, parts[1:])

    def complete(self, partial: str) -> list[str]:
        """返回匹配的命令名（去重、排序）。

        partial 可以带 `/`，也可以不带。匹配范围包括命令名和别名，
        但返回时统一为规范命令名，方便 Tab 补全到可执行命令。
        """
        raw = partial.lstrip("/")
        names = {command.name for key, command in self._commands.items() if key.startswith(raw)}
        return sorted(names)

    def command_names(self) -> list[str]:
        """返回全部规范命令名（去重、排序），供 UI 补全使用。"""
        return sorted({command.name for command in self._commands.values()})
