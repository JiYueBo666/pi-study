# 0005：工具模型上下文与界面展示输出分离

状态：accepted

## 背景

工具输出同时服务两个消费者：模型需要有限、可继续推理的文本；用户需要完整、可读的执行证据。把 Bash 的全部输出直接放进 `ToolResult.content` 会快速占满上下文；先截断再复用同一字符串，又会让 TUI 无法展示完整命令输出和结构化状态。

## 决策

- 在 `agent_core.types` 引入 `ToolOutput(text, content_type)` 与 `ToolExecutionResult`。
- `ToolExecutionResult.output` 是两个消费者的默认值；简单工具只填这一项。
- 可选 `context_output` 是唯一进入 `ai.types.ToolResult.content`、模型请求和 JSONL 会话历史的文本。
- 可选 `display_output` 只通过 `ToolCompleted.display` 交给 CLI/TUI，绝不进入模型历史。
- `details` 保存产品专属结构化字段。Bash 使用 `command`、`exit_code`、`timed_out`；TUI 用这些字段渲染，而不解析一段拼接字符串。
- 迁移期保留 `content=` 与 `.content` 的兼容入口，新的生产代码和消费者必须使用 `ToolOutput` 与 `effective_context_output` / `effective_display_output`。

## 后果

- 模型上下文可以独立限制 Bash 输出；当前限制为 12,000 字符并保留首尾。
- TUI 可以完整、稳定地展示工具证据，并根据 `content_type` 或结构化详情逐步增加不同渲染器。
- `ToolResult` 仍是唯一可持久、可再次发给模型的工具结果；展示信息是瞬时事件数据，当前不会被保存到 JSONL。
- 完整展示输出当前仍保存在内存中。极大 Bash 输出需要后续增加字节上限、文件落盘或流式窗口，不能误认为本决策已解决内存保护。

## 考虑过的替代方案

- **只保留单一 `content` 字符串**：简单但模型上下文限制和完整 UI 展示互相冲突，拒绝。
- **让 TUI 从 `ToolResult.details` 重新构造完整输出**：会把展示协议塞进产品详情，且其他工具难以复用，拒绝。
- **在 `ai.ToolResult` 中保存两份输出**：把 UI 概念带入供应商无关、可持久的模型消息层，拒绝。
