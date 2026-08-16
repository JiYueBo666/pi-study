"""coding_agent.workspace — 路径边界测试（04-boundaries 验收场景 D）。"""

import shutil
from pathlib import Path

import pytest

from coding_agent.workspace import WorkSpace as Workspace
from coding_agent.workspace import WorkspaceError


def test_relative_path_resolves_inside_workspace(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    (tmp_path / "a.txt").write_text("hello")
    assert ws.resolve("a.txt") == (tmp_path / "a.txt").resolve()


def test_absolute_path_inside_allowed(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    target = tmp_path / "b.txt"
    target.write_text("x")
    assert ws.resolve(str(target)) == target.resolve()


def test_escape_rejected(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    for bad in ["../outside", "/etc/passwd"]:
        with pytest.raises(WorkspaceError):
            ws.resolve(bad)


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "pi-study-outside"
    outside.mkdir(exist_ok=True)
    try:
        (outside / "secret.txt").write_text("s")
        (tmp_path / "link").symlink_to(outside, target_is_directory=True)
        ws = Workspace(root=tmp_path)
        with pytest.raises(WorkspaceError):
            ws.resolve("link/secret.txt")
    finally:
        shutil.rmtree(outside, ignore_errors=True)


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    ws.write("sub/x.py", "print(1)")
    content, hint = ws.read("sub/x.py")
    assert content == "print(1)" and hint == ""


def test_read_missing_file_raises(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    with pytest.raises(WorkspaceError, match="not found"):
        ws.read("nope.txt")


def test_read_truncation(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    ws.write("big.txt", "x" * 5000)
    content, hint = ws.read("big.txt", max_bytes=100)
    assert content.startswith("x" * 100)
    assert "truncated" in hint


def test_read_invalid_encoding_raises(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    (tmp_path / "bin.bin").write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(WorkspaceError, match="utf-8"):
        ws.read("bin.bin")


def test_root_accepts_str(tmp_path: Path) -> None:
    ws = Workspace(root=str(tmp_path))
    assert ws.root == tmp_path.resolve()
