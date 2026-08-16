"""coding_agent.tools — 7 个工具行为测试。"""

import asyncio
from pathlib import Path

from ai.types import ToolCallContent
from coding_agent.tools import build_tools
from coding_agent.workspace import WorkSpace as Workspace


def _call(name: str, **args) -> ToolCallContent:
    return ToolCallContent(id="c1", name=name, arguments=args)


async def _exec(tool, **args):
    return await tool.execute(_call(tool.name, **args), asyncio.Event())


def _tools(tmp_path: Path) -> dict:
    return {t.name: t for t in build_tools(Workspace(root=tmp_path))}


def test_read_write_edit_roundtrip(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    r = asyncio.run(_exec(tools["write"], path="new.txt", content="hello"))
    assert not r.is_error
    r = asyncio.run(_exec(tools["read"], path="new.txt"))
    assert r.content == "hello"
    r = asyncio.run(_exec(tools["edit"], path="new.txt", old_text="hello", new_text="world"))
    assert not r.is_error
    assert (tmp_path / "new.txt").read_text() == "world"


def test_edit_requires_unique_match(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    (tmp_path / "f.txt").write_text("a b a")
    r = asyncio.run(_exec(tools["edit"], path="f.txt", old_text="a", new_text="z"))
    assert r.is_error and "times" in r.content
    # 唯一匹配成功
    r = asyncio.run(_exec(tools["edit"], path="f.txt", old_text="b", new_text="q"))
    assert not r.is_error and (tmp_path / "f.txt").read_text() == "a q a"


def test_edit_missing_file_is_error(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    r = asyncio.run(_exec(tools["edit"], path="nope.txt", old_text="x", new_text="y"))
    assert r.is_error


def test_read_missing_file_is_error_result(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    r = asyncio.run(_exec(tools["read"], path="nope.txt"))
    assert r.is_error and "not found" in r.content


def test_escape_rejected_as_error_result(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    r = asyncio.run(_exec(tools["read"], path="/etc/passwd"))
    assert r.is_error and "outside workspace" in r.content


def test_grep_find_ls(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def main():\n    pass\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "util.py").write_text("x = 1")
    tools = _tools(tmp_path)

    g = asyncio.run(_exec(tools["grep"], pattern="def"))
    assert "app.py:1" in g.content

    f = asyncio.run(_exec(tools["find"], pattern="util"))
    assert "sub/util.py" in f.content

    ls = asyncio.run(_exec(tools["ls"]))
    assert "app.py" in ls.content and "sub" in ls.content


def test_bash_runs_in_workspace(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    r = asyncio.run(_exec(tools["bash"], command="pwd && echo hi"))
    assert not r.is_error
    assert str(Workspace(root=tmp_path).root) in r.content
    assert "hi" in r.content


def test_bash_nonzero_exit_is_error(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    r = asyncio.run(_exec(tools["bash"], command="exit 3"))
    assert r.is_error and r.details["exit_code"] == 3


def test_bash_timeout_kills_process(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    r = asyncio.run(_exec(tools["bash"], command="sleep 5", timeout=1))
    assert r.details.get("timed_out")
    assert "timed out" in r.content


def test_missing_parameter_is_error(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    r = asyncio.run(_exec(tools["read"]))
    assert r.is_error and "parameter" in r.content
