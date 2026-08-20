from typing import Any

from pydantic import BaseModel, ValidationError


class ToolArgumentsValidationError(Exception):
    pass


def validate_arguments(
    model_type: type[BaseModel], arguments: dict[str, Any]
) -> BaseModel:
    """校验并规范化模型工具调用的参数。"""
    try:
        return model_type.model_validate(arguments)
    except ValidationError as exc:
        raise ToolArgumentsValidationError(format_validation_errors(exc)) from exc


def format_validation_errors(exc: ValidationError) -> str:
    lines = ["工具参数校验失败:"]

    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"])
        lines.append(f"- {location}: {error['msg']}")
    return "\n".join(lines)
