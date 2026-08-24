"""
coding-agent自定义消息


自定义消息不只是"翻译给 LLM 用的中间格式"那么简单，它本身带来了三个独立的能力：

1. UI 专用渲染。UI 根据 role 字段做分派——bashExecution 用终端样式渲染、compactionSummary
   用摘要卡片渲染，命令、输出、退出码各占一行，互不干扰。如果没有自定义消息，UI 只能拿到
   一段扁平文本，所有渲染花样都得退回到"全是大段文字"。

2. 持久化恢复。session 文件存的是完整的结构化数据。下次启动 Agent 时，UI 能精确还原上次的
   渲染状态——退出码仍然有颜色、命令仍然高亮、截断标识仍然在。如果只存翻译后的扁平文本，
   这些信息重启后就永久丢失了。

3. 精细化可见性控制。因为自定义消息有自己的 role，可以在 convertToLlm 翻译时做特殊处理——
   比如给它加一个 excludeFromContext = true 字段，LLM 就完全看不到这条消息，但 UI 照常渲染。
   标准消息做不到这一点——一旦进了 messages 数组，convertToLlm 就一定会翻译它发给 LLM，
   没有"对 UI 可见但对 LLM 不可见"的余地。
"""

from dataclasses import dataclass
from datetime import datetime

from ai.types import Message


@dataclass(frozen=True, slots=True)
class BashExecutionMessage:
    command: str  # 命令原文
    output: str  # 执行输出
    exitCode: int  # 退出码
    fullOutputPath: str  # 截断时候输出的完整文件路径
    timestamp: datetime
    cancelled: bool = False  # 是否取消
    truncated: bool = False  # 是否截断输出
    excludedFromContext: bool = False  # 是否被排除在LLM上下文之外
    role = "bashExecution"


CustomAgentMessages = BashExecutionMessage

# Coding 产品层能出现在会话中的全部消息：基础 LLM 消息 + 自定义消息。
# 与 pi 的 AgentMessage 不同，这里的联合定义在拥有自定义消息的产品层，
# 保持 agent_core -> ai 的单向依赖不被破坏。
CodingAgentMessage = Message | CustomAgentMessages


def bash_execution_to_text(msg: BashExecutionMessage) -> str:
    """把一次 bash 执行整理成给模型看的文本（对应 pi 的 bashExecutionToText）。"""
    text = f"Ran `{msg.command}`\n"
    if msg.output:
        text += f"```\n{msg.output}\n```"
    else:
        text += "(no output)"
    if msg.cancelled:
        text += "\n\n(command cancelled)"
    elif msg.exitCode is not None and msg.exitCode != 0:
        text += f"\n\nCommand exited with code {msg.exitCode}"
    if msg.truncated and msg.fullOutputPath:
        text += f"\n\n[Output truncated. Full output: {msg.fullOutputPath}]"
    return text
