# 0001：会话持久化与恢复

状态：accepted

## 背景

v0 的 Agent 历史只存在于进程内，退出后对话丢失，无法跨重启继续工作。设计文档 Phase 6 将“会话持久化与恢复”列为第一个候选能力。

Pi 的源码结构显示：会话是通用 Agent 能力，`@earendil-works/pi-agent-core` 提供通用会话抽象（`SessionRepo / SessionStorage / Session`）并自带 JSONL 后端，`coding-agent` 只是消费者。这支持“会话不属于 Coding 产品专属”的判断。

## 决策

- 会话持久化作为通用能力放在 `agent_core/session/`，不放在 `coding_agent`。
- 采用轻量 `SessionStore` 协议，不引入完整 Pi 风格 `SessionRepo / SessionStorage / Session` 分层。
- 首个后端为 JSONL：`JsonlSessionStore`，文件存放在工作区 `.pi-study/sessions/<session_id>.jsonl`。
- 只持久化 `ai.types.Message`（`UserMessage` / `AssistantMessage` / `ToolResult`）；结构化 bash 消息留到后续。
- 自动保存：每个 prompt 结束后（含取消）整体原子写。
- CLI 提供 `--resume <id>`、`--list-sessions`、`--forget <id>`。
- 会话 ID 使用短 ID（如 `sess_20260817-063216-3b0d`），`--resume` / `--forget` 支持唯一前缀匹配。
- 恢复时校验会话 `cwd` 与当前工作区一致，不一致拒绝恢复。
- `SessionMeta` 不保存模型字段：模型可以在会话中切换，模型信息保留在每条 `AssistantMessage` 中。

## 后果

- 非 Coding Agent 未来可以复用 `agent_core/session`，不需要依赖 Coding 产品层。
- `coding_agent` 只负责产品决策：会话目录位置、保存时机、CLI 命令。
- 本地磁盘会保存原始对话 transcript（用户输入、模型回复、工具输出），需要隐私说明；当前不承诺加密或自动清理。
- JSONL 后端足够满足 P1；未来需要更强查询/并发/分叉时再引入 SQLite 或完整 Session 分层。

## 考虑过的替代方案

- **把 SessionStore 放在 `coding_agent`**：与会话是通用 Agent 能力的事实不符，非 Coding 产品无法复用，拒绝。
- **使用 SQLite 后端**：功能更强，但 P1 规模下 JSONL 更简单、可读、易调试，推迟。
- **完整模仿 Pi 的 `SessionRepo / SessionStorage / Session` 分层**：为后续分叉/压缩铺路，但当前复杂度不必要，推迟。
- **让 `Agent` 自己自动保存**：保存时机是产品/运行模式决策，不应写死在通用 Agent 内，拒绝。
