from dataclasses import dataclass

from ai.types import ToolCallContent

ToolApprovalResult = tuple[bool, str]


@dataclass(frozen=True, slots=True)
class ToolApprovalRequest:
    request_id: str
    tool_name: str
    tool_description: str
    call: ToolCallContent


@dataclass(frozen=True, slots=True)
class ToolApprovalRequested:
    request: ToolApprovalRequest


@dataclass(frozen=True, slots=True)
class ToolApprovalCompleted:
    call: ToolCallContent
    approved: bool


CodingEvent = ToolApprovalRequested | ToolApprovalCompleted
