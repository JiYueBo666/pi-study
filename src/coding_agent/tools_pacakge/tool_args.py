from pydantic import BaseModel, ConfigDict, Field

"""
该文件定义工具系统中的工具需要的格式。由Pydantic管理。
"""


class ToolArgs(BaseModel):
    """
    拒绝模型生成未定义参数
    允许 不严格字段，例如120.0-->120
    """

    model_config = ConfigDict(extra="forbid", strict=False)


class ReadArgs(ToolArgs):
    path: str = Field(min_length=1, description="要读取的文件路径")


class WriteArgs(ToolArgs):
    path: str = Field(min_length=1, description="要写入的文件路径")
    content: str = Field(description="要写入文件的完整内容")


class EditArgs(ToolArgs):
    path: str = Field(min_length=1, description="要编辑的文件路径")
    old_text: str = Field(description="要替换的原文本，必须唯一匹配")
    new_text: str = Field(description="替换后的新文本")


class GrepArgs(ToolArgs):
    pattern: str = Field(min_length=1, description="要搜索的文本")
    path: str = Field(default=".", description="搜索的目录路径，默认为工作区根目录")


class FindArgs(ToolArgs):
    pattern: str = Field(min_length=1, description="文件名匹配文本")


class ListArgs(ToolArgs):
    path: str = Field(default=".", description="要列出的目录路径，默认为工作区根目录")


class BashArgs(ToolArgs):
    command: str = Field(min_length=1, description="要执行的 shell 命令")
    timeout: float = Field(
        default=120, ge=1, le=600, description="超时时间，单位为秒，范围 1 到 600"
    )
