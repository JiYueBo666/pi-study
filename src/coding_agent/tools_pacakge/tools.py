"""
coding agent tools
"""

import asyncio
import os
import signal
from pathlib import Path

from pydantic import BaseModel

from agent_core.types import ProgressSink, ToolExecutionResult
from ai.types import ToolCallContent
from ai.utils.validations import ToolArgumentsValidationError, validate_arguments
from coding_agent.tools_pacakge.tool_args import (
    BashArgs,
    EditArgs,
    FindArgs,
    GrepArgs,
    ListArgs,
    ReadArgs,
    WriteArgs,
)
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


"""
进行具体工具定义
工具需要定义:
1.名字
2.工具描述
3.参数模型
4.工作区

工具通过满足AgentTool的协议被定义为AgentTool类型

"""


class ToolBase:
    """基类：execute 统一捕获 ToolFailure/WorkspaceError → is_error 结果。"""

    name: str
    description: str
    args_model: type[BaseModel]
    is_safe: bool
    workspace: Workspace

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace

    async def execute(
        self,
        call: ToolCallContent,
        cancel: asyncio.Event,
        on_progress: ProgressSink | None = None,
    ):

        try:
            """
            先进行参数校验 ,之后进行具体执行
            具体执行为类方法，由各个具体工具实现
            """
            args = validate_arguments(self.args_model, call.arguments)
            return await self._run(call, args, on_progress)
        except ToolArgumentsValidationError as exc:
            return ToolExecutionResult(
                content=str(exc),
                details={"validation_error": True, "tool": call.name},
                is_error=True,
            )
        except ToolFailure as exc:
            return ToolExecutionResult(
                content=str(exc), details={"error": str(exc)}, is_error=True
            )
        except WorkspaceError as exc:
            return ToolExecutionResult(
                content=str(exc), details={"error": str(exc)}, is_error=True
            )

    async def _run(
        self, call, args: BaseModel, on_progress: ProgressSink | None = None
    ) -> ToolExecutionResult:
        raise NotImplementedError


class ReadTool(ToolBase):
    name: str = "read"
    description: str = "Tool to use to read file"
    args_model: type[BaseModel] = ReadArgs
    is_safe = True

    async def _run(
        self,
        call: ToolCallContent,
        args: ReadArgs,
        on_progress: ProgressSink | None = None,
    ):
        content, hint = self.workspace.read(args.path)
        return ToolExecutionResult(
            content=content, details={"path": args.path, "truncated": bool(hint)}
        )


class WriteTool(ToolBase):
    name = "write"
    description = "Tool to write a file"
    args_model: type[BaseModel] = WriteArgs
    is_safe = False

    async def _run(
        self,
        call: ToolCallContent,
        args: WriteArgs,
        on_progress: ProgressSink | None = None,
    ) -> ToolExecutionResult:
        self.workspace.write(args.path, args.content)

        return ToolExecutionResult(
            content="File write successfully",
            details={
                "path": args.path,
                "status": "successful",
            },
        )


class EditTool(ToolBase):
    name = "edit"
    description = "替换文件中一段文本（旧文本必须唯一匹配）。"
    args_model: type[BaseModel] = EditArgs
    is_safe = False

    async def _run(
        self,
        call: ToolCallContent,
        args: EditArgs,
        on_progress: ProgressSink | None = None,
    ) -> ToolExecutionResult:
        target = self.workspace.resolve(args.path)

        try:
            current = target.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ToolFailure(f"file not found: {args.path}") from None

        count = current.count(args.old_text)

        if count == 0:
            raise ToolFailure(f"old text not found in {args.path}")

        if count > 1:
            raise ToolFailure(f"old text matches {count} times; make it unique")

        target.write_text(
            current.replace(args.old_text, args.new_text, 1),
            encoding="utf-8",
        )

        return ToolExecutionResult(
            content=f"edited {args.path}: replaced 1 occurrence",
            details={"path": args.path},
        )


class GrepTool(ToolBase):
    name = "grep"
    description = "在工作区内搜索文本，返回最多 200 条匹配。"
    args_model: type[BaseModel] = GrepArgs
    is_safe = True

    async def _run(
        self,
        call: ToolCallContent,
        args: GrepArgs,
        on_progress: ProgressSink | None = None,
    ) -> ToolExecutionResult:
        target = self.workspace.resolve(args.path)

        if not target.is_dir():
            raise ToolFailure(f"not a directory: {args.path}")

        matches: list[str] = []

        for base, _, files in os.walk(target):
            for filename in files:
                file_path = Path(base) / filename

                try:
                    lines = file_path.read_text(encoding="utf-8").splitlines()
                except (UnicodeDecodeError, OSError):
                    continue

                for lineno, line in enumerate(lines, 1):
                    if args.pattern in line:
                        rel = file_path.relative_to(self.workspace.root)
                        matches.append(f"{rel}:{lineno}:{line}")

                        if len(matches) >= MAX_GREP_MATCHES:
                            return ToolExecutionResult(
                                content="\n".join(matches),
                                details={
                                    "path": args.path,
                                    "truncated": True,
                                },
                            )

        if not matches:
            return ToolExecutionResult(
                content=f"no matches for {args.pattern!r}",
                details={"path": args.path},
            )

        return ToolExecutionResult(
            content="\n".join(matches),
            details={"path": args.path},
        )


class FindTool(ToolBase):
    name = "find"
    description = "按文件名查找工作区内文件。"
    args_model: type[BaseModel] = FindArgs
    is_safe = True

    async def _run(
        self,
        call: ToolCallContent,
        args: FindArgs,
        on_progress: ProgressSink | None = None,
    ) -> ToolExecutionResult:
        found: list[str] = []

        for base, dirs, files in os.walk(self.workspace.root):
            dirs[:] = [
                directory
                for directory in dirs
                if not directory.startswith(".")
                and directory not in {"node_modules", "__pycache__"}
            ]

            for filename in files:
                if args.pattern in filename:
                    found.append(
                        str(Path(base).relative_to(self.workspace.root) / filename)
                    )

                    if len(found) >= MAX_LS_ENTRIES:
                        return ToolExecutionResult(
                            content="\n".join(found),
                            details={"truncated": True},
                        )

        if not found:
            return ToolExecutionResult(
                content=f"no files match {args.pattern!r}",
                details={},
            )

        return ToolExecutionResult(
            content="\n".join(found),
            details={},
        )


class ListTool(ToolBase):
    name = "ls"
    description = "列出目录条目（最多 500 条）。"
    args_model: type[BaseModel] = ListArgs
    is_safe = True

    async def _run(
        self,
        call: ToolCallContent,
        args: ListArgs,
        on_progress: ProgressSink | None = None,
    ) -> ToolExecutionResult:
        target = self.workspace.resolve(args.path)

        if not target.is_dir():
            raise ToolFailure(f"not a directory: {args.path}")

        try:
            entries = sorted(os.listdir(target))
        except OSError as exc:
            raise ToolFailure(f"cannot list {args.path}: {exc}") from None

        if len(entries) > MAX_LS_ENTRIES:
            return ToolExecutionResult(
                content="\n".join(entries[:MAX_LS_ENTRIES]),
                details={
                    "path": args.path,
                    "truncated": True,
                },
            )

        return ToolExecutionResult(
            content="\n".join(entries) if entries else "(empty directory)",
            details={"path": args.path},
        )


class BashTool(ToolBase):
    name = "bash"
    description = "在工作区目录运行 shell 命令。返回退出码、stdout、stderr。"
    args_model: type[BaseModel] = BashArgs
    is_safe = False

    async def _run(
        self,
        call: ToolCallContent,
        args: BashArgs,
        on_progress: ProgressSink | None = None,
    ) -> ToolExecutionResult:
        proc = await asyncio.create_subprocess_shell(
            args.command,
            cwd=str(self.workspace.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )

        if proc.stdout is None:
            raise RuntimeError("stdout没有被PIPE捕获")

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def read_stdout():
            await _read_stream(proc.stdout, on_progress, stdout_lines)

        async def read_stderr():
            await _read_stream(proc.stderr, None, stderr_lines)  # stderr 也可回调，你定

        try:
            await asyncio.wait_for(
                asyncio.gather(read_stdout(), read_stderr()),
                timeout=args.timeout,
            )
        except TimeoutError:
            await _kill_process_group(proc)
            await proc.wait()
            return ToolExecutionResult(
                content="[command timed out]",
                details={
                    "command": args.command,
                    "exit_code": proc.returncode,
                    "timed_out": True,
                },
                is_error=False,  # 超时不是"错误"，模型可继续（04-boundaries 失败分类）
            )
        except asyncio.CancelledError:
            await _kill_process_group(proc)
            await proc.wait()
            raise

        await proc.wait()
        text = "".join(stdout_lines)
        if stderr_lines:
            text += "\nstderr: " + "".join(stderr_lines)
        return ToolExecutionResult(
            content=text,
            details={"command": args.command, "exit_code": proc.returncode},
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


def build_tools(workspace: Workspace) -> list[ToolBase]:
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


async def _read_stream(stream, sink, buffer):
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace")
        buffer.append(text)  # 内容保留换行
        if sink:
            sink(text.rstrip("\n"))
