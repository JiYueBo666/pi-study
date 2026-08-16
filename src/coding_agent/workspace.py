from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(Exception):
    pass


@dataclass(slots=True, frozen=True)
class WorkSpace:
    root: str | Path

    def __post_init__(self):
        normalized = Path(self.root).expanduser().resolve()  # 兼容 str 与 Path
        if not normalized.is_dir():
            raise WorkspaceError(f"root 解析为 {normalized}，不是一个文件夹")

        object.__setattr__(self, "root", normalized)

    def resolve(self, path: str):
        """
        路径解析和越界防护
        """
        candidate = Path(path)

        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if not resolved.is_relative_to(self.root):
            raise WorkspaceError(f"path outside workspace: {path}")
        return resolved

    def read(self, path: str, *, max_bytes: int = 100 * 1024) -> tuple[str, str]:
        """读取文件；返回 (内容, 截断提示)。文件缺失/目录/非法编码 -> WorkspaceError。"""

        target = self.resolve(path)
        try:
            data = target.read_bytes()
        except FileNotFoundError:
            raise WorkspaceError(f"file not found: {path}") from None
        except IsADirectoryError:
            raise WorkspaceError(f"is a directory: {path}") from None

        truncated = len(data) > max_bytes
        data = data[:max_bytes]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise WorkspaceError(f"file is not valid utf-8: {path}") from None

        hint = f"[output truncated at {max_bytes} bytes]" if truncated else ""
        return text + (f"\n{hint}" if hint else ""), hint

    def write(self, path: str, content: str) -> None:
        """整体覆盖文件；父目录不存在则创建。"""

        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
