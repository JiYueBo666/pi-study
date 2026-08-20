"""
定义一些工具调用配置
"""

import tomllib
from enum import Enum
from pathlib import Path


class ApprovalMode(Enum):
    AutoAccept = "autoAccept"
    ASK = "ask"


class RejectResponse(Enum):
    """
    定义工具拒绝后的行为:
    继续循环，还是停止流程
    """

    CONTINUE = "continue"
    STOP = "stop"


_CONFIG_PATH = Path(__file__).resolve().parent.parent / "custom.toml"


def load_reject_prompt_map() -> dict[str, str]:
    with _CONFIG_PATH.open("rb") as file:
        config = tomllib.load(file)

    prompts = config.get("reject_prompt")
    if not isinstance(prompts, dict):
        raise ValueError("custom.toml 缺少 [reject_prompt] 配置")

    result: dict[str, str] = {}
    for key, value in prompts.items():
        if not isinstance(value, str):
            raise ValueError(f"reject_prompt.{key} 必须是字符串")
        result[key] = value
    return result
