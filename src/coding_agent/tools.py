"""
coding agent tools
"""

import asyncio
import os
import signal
from pathlib import Path

from agent_core.types import AgentTool, ToolExecutionResult
from ai.types import ToolCallContent
from coding_agent.workspace import WorkSpace as Workspace
from coding_agent.workspace import WorkspaceError

MAX_GREP_MATCHES = 200
MAX_LS_ENTRIES = 500
DEFAULT_TIMEOUT = 120  # 秒
MAX_TIMEOUT = 600


class ToolFailure(Exception):
    """
    参数错误等确定性失败
    """

    pass


class ToolBase(AgentTool):
    """基类：execute 统一捕获 ToolFailure/WorkspaceError → is_error 结果。"""

    workspace: Workspace

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    def _arg(self, call: ToolCallContent, key: str) -> str:  # 取参，非 str 抛 ToolFailure
        value = call.arguments.get(key)

        if not isinstance(value, str):
            raise ToolFailure(f"parameter '{key}' must be a string")
        return value

    async def execute(self, call: ToolCallContent, cancel: asyncio.Event):
        # try: self._run(call) except ...: is_error
        try:
            return await self._run(call)
        except ToolFailure as exc:
            return ToolExecutionResult(content=str(exc), details={"error": str(exc)}, is_error=True)
        except WorkspaceError as exc:
            return ToolExecutionResult(content=str(exc), details={"error": str(exc)}, is_error=True)

    async def _run(self, call) -> ToolExecutionResult:
        raise NotImplementedError


class ReadTool(ToolBase):
    name: str = "read"
    description: str = "Tool to use to read file"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "file path to read"}},
        "required": ["path"],
    }

    async def _run(self, call: ToolCallContent):
        path = self._arg(call, "path")
        content, hint = self.workspace.read(path)
        return ToolExecutionResult(content=content, details={"path": path, "truncated": bool(hint)})


class WriteTool(ToolBase):
    name: str = "write"
    description: str = "Tool to write a file"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "file path to write"},
            "content": {"type": "string", "description": "the content to write"},
        },
        "required": ["path", "content"],
    }

    async def _run(self, call: ToolCallContent):
        path, content = self._arg(call, "path"), self._arg(call, "content")
        try:
            self.workspace.write(path, content)
        except ToolFailure:
            return ToolExecutionResult(content="write failed", is_error=True)
        return ToolExecutionResult(content="File write successfully", details={"status": "successful"})


class EditTool(ToolBase):
    name: str = "edit"
    description: str = "替换文件中一段文本（旧文本必须唯一匹配）。"
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "file path to edit"},
            "old_text": {
                "type": "string",
                "description": "The original text to be replaced",
            },
            "new_text": {
                "type": "string",
                "description": "The new text after replacement",
            },
        },
        "required": ["path", "old_text", "new_text"],
    }

    async def _run(self, call: ToolCallContent):
        path = self._arg(call, "path")
        old_text = self._arg(call, "old_text")
        new_text = self._arg(call, "new_text")

        target = self.workspace.resolve(path)
        try:
            current = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ToolFailure(f"file not found: {path}") from None
        count = current.count(old_text)

        if count == 0:
            raise ToolFailure(f"old text not found in {path}")
        if count > 1:
            raise ToolFailure(f"old text matches {count} times; make it unique")
        target.write_text(current.replace(old_text, new_text, 1), encoding="utf-8")
        return ToolExecutionResult(content=f"edited {path}: replaced 1 occurrence", details={"path": path})


class GrepTool(ToolBase):
    name: str = "grep"
    description: str = "在工作区内搜索文本，返回最多 200 条匹配（path:行号:内容）。"
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "要搜索的文本"},
            "path": {"type": "string", "description": "起始目录（默认工作区根）"},
        },
        "required": ["pattern"],
    }

    async def _run(self, call: ToolCallContent):
        pattern = self._arg(call, "pattern")
        path = self._arg(call, "path") if call.arguments.get("path") else "."
        target = self.workspace.resolve(path)
        if not target.is_dir():
            raise ToolFailure(f"not a directory: {path}")

        matches: list[str] = []
        for base, _, files in os.walk(target):
            for filename in files:
                file_path = Path(base) / filename
                try:
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                except (UnicodeDecodeError, OSError):
                    continue  # 二进制/不可读文件跳过，不崩溃
                for lineno, line in enumerate(lines, 1):
                    if pattern in line:
                        rel = file_path.relative_to(self.workspace.root)
                        matches.append(f"{rel}:{lineno}:{line}")
                        if len(matches) >= MAX_GREP_MATCHES:
                            return ToolExecutionResult(
                                content="\n".join(matches) + f"\n[truncated at {MAX_GREP_MATCHES} matches]",
                                details={"path": path, "truncated": True},
                            )
        if not matches:
            return ToolExecutionResult(content=f"no matches for {pattern!r}", details={"path": path})
        return ToolExecutionResult(content="\n".join(matches), details={"path": path})


class FindTool(ToolBase):
    name: str = "find"
    description: str = "按文件名查找工作区内文件（子串匹配）。"
    parameters = {
        "type": "object",
        "properties": {"pattern": {"type": "string", "description": "文件名子串"}},
        "required": ["pattern"],
    }

    async def _run(self, call: ToolCallContent):
        pattern = self._arg(call, "pattern")
        found: list[str] = []
        for base, dirs, files in os.walk(self.workspace.root):
            # 跳过隐藏目录与常见构建目录，避免噪音
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__"}]
            for filename in files:
                if pattern in filename:
                    found.append(str(Path(base).relative_to(self.workspace.root) / filename))
                    if len(found) >= MAX_LS_ENTRIES:
                        return ToolExecutionResult(
                            content="\n".join(found) + f"\n[truncated at {MAX_LS_ENTRIES} entries]",
                            details={"truncated": True},
                        )
        if not found:
            return ToolExecutionResult(content=f"no files match {pattern!r}", details={})
        return ToolExecutionResult(content="\n".join(found), details={})


class ListTool(ToolBase):
    name: str = "ls"
    description: str = "列出目录条目（最多 500 条）。"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "目录路径（默认工作区根）"}},
    }

    async def _run(self, call: ToolCallContent):
        path = self._arg(call, "path") if call.arguments.get("path") else "."
        target = self.workspace.resolve(path)
        if not target.is_dir():
            raise ToolFailure(f"not a directory: {path}")
        try:
            entries = sorted(os.listdir(target))
        except OSError as exc:
            raise ToolFailure(f"cannot list {path}: {exc}") from None
        if len(entries) > MAX_LS_ENTRIES:
            return ToolExecutionResult(
                content="\n".join(entries[:MAX_LS_ENTRIES]) + f"\n[truncated at {MAX_LS_ENTRIES} entries]",
                details={"path": path, "truncated": True},
            )
        if not entries:
            return ToolExecutionResult(content="(empty directory)", details={"path": path})
        return ToolExecutionResult(content="\n".join(entries), details={"path": path})


class BashTool(ToolBase):
    name: str = "bash"
    description: str = (
        "在工作区目录运行 shell 命令（本地 shell 不是安全边界）。"
        "返回退出码、stdout、stderr；可设 timeout（秒，默认 120，最大 600）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "number", "description": "秒，默认 120"},
        },
        "required": ["command"],
    }

    async def _run(self, call: ToolCallContent):
        command = self._arg(call, "command")
        raw_timeout = call.arguments.get("timeout", DEFAULT_TIMEOUT)
        try:
            timeout = int(raw_timeout)
        except (TypeError, ValueError):
            timeout = DEFAULT_TIMEOUT
        timeout = min(max(timeout, 1), MAX_TIMEOUT)

        # 独立进程组：超时/取消时能终止整个组（04-boundaries）
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.workspace.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            await _kill_process_group(proc)
            await proc.wait()
            return ToolExecutionResult(
                content="[command timed out]",
                details={
                    "command": command,
                    "exit_code": proc.returncode,
                    "timed_out": True,
                },
                is_error=False,  # 超时不是"错误"，模型可继续（04-boundaries 失败分类）
            )
        except asyncio.CancelledError:
            # Ctrl+C 取消：终止整个进程组后再传播（04-boundaries 取消语义）
            await _kill_process_group(proc)
            await proc.wait()
            raise

        text = stdout.decode("utf-8", errors="replace")
        if stderr:
            text += ("\n" if text else "") + "stderr: " + stderr.decode("utf-8", errors="replace")
        return ToolExecutionResult(
            content=text,
            details={"command": command, "exit_code": proc.returncode},
            is_error=proc.returncode != 0,
        )


async def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


def build_tools(workspace: Workspace) -> list[AgentTool]:
    """组装 coding_agent 全部工具。"""

    return [
        ReadTool(workspace),
        WriteTool(workspace),
        EditTool(workspace),
        GrepTool(workspace),
        FindTool(workspace),
        ListTool(workspace),
        BashTool(workspace),
    ]
