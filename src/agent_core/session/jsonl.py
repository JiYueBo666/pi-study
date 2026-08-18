import json
import os
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_core.session.types import SessionError, SessionMeta
from ai.types import (
    AssistantMessage,
    CompactionSummaryMessage,
    Message,
    TextContent,
    ThinkingContent,
    ToolCallContent,
    ToolResult,
    UserMessage,
)


class JsonlSessionStore:
    """JSONL 版本的 SessionStore（P1 核心实现）。"""

    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return self.sessions_dir / f"{session_id}.jsonl"

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        """拒绝把会话 ID 当作路径使用，保持存储在 sessions_dir 内。"""
        if not re.fullmatch(r"sess_[A-Za-z0-9-]+", session_id):
            raise SessionError(f"invalid session id: {session_id}")

    @staticmethod
    def _validate_prefix(prefix: str) -> None:
        if not prefix or not re.fullmatch(r"[A-Za-z0-9_-]+", prefix):
            raise SessionError(f"invalid session id: {prefix}")

    def save(self, meta: SessionMeta, messages: Sequence[Message]) -> None:
        """原子写：先写临时文件，再替换。

        save 会自动修正 meta 的 message_count 和 updated_at，
        调用方不需要手动维护这两个字段。
        """
        meta = replace(
            meta,
            message_count=len(messages),
            updated_at=datetime.now(UTC),
        )
        path = self._session_path(meta.id)
        temp_path = path.with_name(path.name + ".tmp")

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(self._meta_to_dict(meta)) + "\n")
                for m in messages:
                    f.write(json.dumps(self._message_to_dict(m)) + "\n")
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def load(self, session_id: str) -> tuple[SessionMeta, list[Message]]:
        """读取会话；只忽略尾部不完整行，中间坏行报错。"""
        path = self._session_path(session_id)

        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            raise SessionError(f"session not found: {session_id}") from None

        if not lines:
            raise SessionError(f"session not found: {session_id}")

        try:
            meta_dict = json.loads(lines[0])
            meta = self._meta_from_dict(meta_dict)
        except json.JSONDecodeError:
            raise SessionError(f"meta损坏：{session_id}") from None
        if meta.id != session_id:
            raise SessionError(f"session id mismatch: {meta.id} != {session_id}")

        messages = []
        for idx, line in enumerate(lines[1:], start=1):
            if not line.strip():
                continue
            try:
                messages.append(self._message_from_dict(json.loads(line)))
            except json.JSONDecodeError:
                if idx == len(lines) - 1:
                    break
                raise SessionError(f"corrupt session: {session_id}") from None

        return meta, messages

    def list(self) -> list[SessionMeta]:
        """只读首行 meta，按 updated_at 倒序。"""
        metas = []
        for file in self.sessions_dir.iterdir():
            if not file.name.endswith(".jsonl"):
                continue
            try:
                with open(file, encoding="utf-8") as f:
                    meta_dict = json.loads(f.readline())
                metas.append(self._meta_from_dict(meta_dict))
            except Exception:
                continue
        metas.sort(key=lambda m: m.updated_at, reverse=True)
        return metas

    def delete(self, session_id: str) -> None:
        path = self._session_path(session_id)
        try:
            path.unlink()
        except FileNotFoundError:
            raise SessionError(f"session not found: {session_id}") from None

    def resolve(self, id_or_prefix: str) -> str:
        self._validate_prefix(id_or_prefix)
        if re.fullmatch(r"sess_[A-Za-z0-9-]+", id_or_prefix):
            exact = self._session_path(id_or_prefix)
            if exact.exists():
                return id_or_prefix

        candidates = [
            f.name for f in self.sessions_dir.iterdir() if f.name.endswith(".jsonl") and f.name.startswith(id_or_prefix)
        ]
        if not candidates:
            raise SessionError(f"session not found: {id_or_prefix}")
        if len(candidates) > 1:
            raise SessionError(f"ambiguous session prefix: {id_or_prefix} (candidates: {candidates})")
        return Path(candidates[0]).stem

    # === SessionMeta 序列化 ===

    def _meta_to_dict(self, meta: SessionMeta) -> dict:
        return {
            "id": meta.id,
            "cwd": meta.cwd,
            "created_at": meta.created_at.isoformat(),
            "updated_at": meta.updated_at.isoformat(),
            "max_turns": meta.max_turns,
            "message_count": meta.message_count,
            "version": meta.version,
        }

    def _meta_from_dict(self, d: dict) -> SessionMeta:
        return SessionMeta(
            id=d["id"],
            cwd=d["cwd"],
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            max_turns=d["max_turns"],
            message_count=d["message_count"],
            version=d.get("version", 1),
        )

    # === Message 序列化 ===

    def _message_to_dict(self, message: Message) -> dict:
        if isinstance(message, UserMessage):
            return {
                "type": "message",
                "role": "user",
                "content": message.content,
                "timestamp": message.timestamp.isoformat(),
            }

        if isinstance(message, CompactionSummaryMessage):
            return {
                "type": "message",
                "role": "compactionSummary",
                "summary": message.summary,
                "timestamp": message.timestamp.isoformat(),
                "tokens_before": message.tokens_before,
            }

        if isinstance(message, AssistantMessage):
            return {
                "type": "message",
                "role": "assistant",
                "content": [self._content_to_dict(c) for c in message.content],
                "timestamp": message.timestamp.isoformat(),
                "api": message.api,
                "provider": message.provider,
                "model": message.model,
                "usage": message.usage,
                "stopReason": message.stopReason,
                "errorMessage": message.errorMessage,
            }

        if isinstance(message, ToolResult):
            return {
                "type": "message",
                "role": "toolResult",
                "toolCallId": message.toolCallId,
                "toolName": message.toolName,
                "content": [self._content_to_dict(c) for c in message.content],
                "details": message.details,
                "timestamp": message.timestamp.isoformat(),
                "isError": message.isError,
            }

        raise SessionError(f"unknown message type: {type(message).__name__}")

    def _message_from_dict(self, data: dict) -> Message:
        role = data.get("role")

        if role == "user":
            return UserMessage(
                content=data["content"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
            )

        if role == "assistant":
            return AssistantMessage(
                content=[self._content_from_dict(c) for c in data["content"]],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                api=data["api"],
                provider=data["provider"],
                model=data["model"],
                usage=data["usage"],
                stopReason=data["stopReason"],
                errorMessage=data.get("errorMessage"),
            )

        if role == "toolResult":
            return ToolResult(
                toolCallId=data["toolCallId"],
                toolName=data["toolName"],
                content=[self._content_from_dict(c) for c in data["content"]],
                details=data.get("details", {}),
                timestamp=datetime.fromisoformat(data["timestamp"]),
                isError=data.get("isError", False),
            )
        if role == "compactionSummary":
            return CompactionSummaryMessage(
                summary=data["summary"],
                timestamp=datetime.fromisoformat(data["timestamp"]),
                tokens_before=data.get("tokens_before", 0),
            )

        raise SessionError(f"unknown message role: {role}")

    # === Content block 序列化 ===

    def _content_to_dict(self, content: Any) -> dict:
        if isinstance(content, TextContent):
            return {"type": "text", "text": content.text}
        if isinstance(content, ThinkingContent):
            return {"type": "thinking", "thinking": content.thinking}
        if isinstance(content, ToolCallContent):
            return {
                "type": "toolCall",
                "id": content.id,
                "name": content.name,
                "arguments": content.arguments,
            }
        raise SessionError(f"unknown content type: {type(content).__name__}")

    def _content_from_dict(self, data: dict) -> Any:
        content_type = data.get("type")
        if content_type == "text":
            return TextContent(text=data["text"])
        if content_type == "thinking":
            return ThinkingContent(thinking=data["thinking"])
        if content_type == "toolCall":
            return ToolCallContent(
                id=data["id"],
                name=data["name"],
                arguments=data["arguments"],
            )
        raise SessionError(f"unknown content type: {content_type}")
