from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ai.types import Message

"""
会话本身有元数据

会话ID
创建时间
修改时间
会话条数
历史消息

"""

"""
历史消息应该包含

对话角色
对话内容
对话时间
使用的模型
思考强度（暂时不涉及）
"""

"""
Agent拥有会话，可以加载和恢复。

所以要有一个操作会话的结构。叫Sessionstore
"""


@dataclass(frozen=True, slots=True)
class SessionMeta:
    id: str = field()
    cwd: str
    created_at: datetime
    updated_at: datetime
    # 兼容旧会话元数据；None 表示由工具调用驱动且不设轮数上限。
    max_turns: int | None = None
    message_count: int = 0
    version: int = 1


class SessionError(Exception):
    """
    会话存储错误
    """


class SessionStore(Protocol):
    def save(self, meta: SessionMeta, messages: Sequence[Message]) -> None: ...
    def load(self, session_id: str) -> tuple[SessionMeta, list[Message]]: ...
    def list(self) -> list[SessionMeta]: ...
    def delete(self, session_id: str) -> None: ...
    def resolve(self, id_or_prefix: str) -> str: ...
