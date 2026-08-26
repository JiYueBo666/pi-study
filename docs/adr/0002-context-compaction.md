# 0002：上下文压缩

状态：accepted

## 背景

长对话会让模型上下文超限、成本上升、质量下降。P1 已实现会话持久化，但历史只增不减。设计文档 Phase 6 将“上下文选择与压缩”列为候选能力，Pi 在 `pi-agent-core` 中提供了 compaction 实现，可作为参考。

## 决策

- 上下文压缩作为通用能力放在 `agent_core/compaction.py`，不放在 Coding 产品层。
- 新增 `CompactionSummaryMessage` 到 `ai.types`，作为被压缩旧历史的替代消息；发送给模型时转换为 `user` 消息。
- 自动触发使用模型配置的真实上下文窗口和 Provider 返回的 `prompt_tokens`；缺少任一值时不自动压缩，不再用字符数 / 4 猜测。
- 切点按轮次边界保留最近轮次，不以估算 token 决定切点。
- 自动压缩时机：每次模型调用前，由 `run_loop` 的 `compactor` 回调触发。
- 手动压缩：`/compact` 命令调用同一 `compact_messages`，`force=True` 时只要有多个轮次就保留最后一个轮次、压缩之前全部历史。
- 压缩失败必须安全返回原消息，绝不丢对话。
- 新增 `ContextCompacted` 事件，供 CLI/TUI 展示压缩发生。

## 后果

- 长对话可以继续运行，但摘要会丢失部分细节；需要真实使用验证 `keep_recent_turns` 和摘要 prompt。
- `ai.types.Message` 联合类型增加一种消息，`openai_model` 和 `JsonlSessionStore` 都必须支持。
- `run_loop` 增加 `compactor` 回调，`Agent` 负责同步压缩后的消息状态。
- 后续可升级为增量摘要、token 精确切点、摘要缓存。

## 考虑过的替代方案

- **不压缩，只截断**：实现简单但会丢失关键上下文，拒绝。
- **用普通 `UserMessage` 表示摘要**：改动最小但无法区分摘要与真实用户输入，拒绝。
- **Pi 风格 token 精确定位 + 增量摘要**：更强大但当前复杂度不必要，推迟。
- **只在 `Agent.run` 前压缩一次**：长任务中途不会压缩，拒绝。
