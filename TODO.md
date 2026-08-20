# TODO

按推荐优先级整理的下一步迭代事项。

## 已确定的方案决策

- P0：代码 + 测试 + 同步更新设计文档（`03-contracts` 增加 `ToolUpdated` / `on_progress`）
- P1 会话归属：`agent_core/session/` 通用会话层（轻量 `SessionStore` + JSONL 后端），`coding_agent` 只做产品组装
- P1 存储位置：工作区 `.pi-study/sessions/`
- P1 格式：JSONL
- P1 恢复方式：自动保存 + 显式 `--resume <id>`
- P1 持久化范围：只持久化 Agent 历史消息（User/Assistant/ToolResult），结构化 bash 留到 P4
- P1 CLI：额外提供 `--list-sessions` / `--forget <id>`
- P1 保存时机：每个 prompt 结束后整体保存
- P1 会话 ID：短 ID（如 `sess_20260816-1716-a1b2c3`），`--resume` 支持唯一前缀匹配
- P1 工作区不匹配：拒绝恢复
- P1 损坏文件策略：只忽略尾部不完整行，中间坏行报错
- P1 文档：新增 ADR 0001 记录会话持久化决策

---

## P0：收尾当前“工具进度流”改动（已完成）

- [x] 修复 `src/coding_agent/render.py` import 顺序（ruff I001）
- [x] `_execute_tool_with_progress` 用 `try/finally` 保证 `update_tasks` 一定被 gather
- [x] 为 `ToolUpdated` / bash 实时输出补测试：
  - [x] agent_core：fake tool 调 `on_progress`，断言 `ToolUpdated` 按序发出
  - [x] coding_agent：bash 分步输出 → `on_progress` 收到行
  - [x] 超时 / 取消路径进度流正常收尾
- [x] 更新 `docs/design/03-contracts.md`：
  - [x] `AgentTool.execute` 增加可选 `on_progress`
  - [x] 事件表增加 `tool_updated`
  - [x] 不变量说明：进度事件只用于展示，不进入历史
- [x] 跑通 `pytest -q`、`ruff check`、`ruff format --check`、`pyright`
- [x] 提交 v0.1 增量

## P1：会话持久化与恢复（代码与文档已完成，测试待补）

### 存储与格式

- [x] 目录：`<workspace>/.pi-study/sessions/<session_id>.jsonl`
- [x] `.gitignore` 增加 `.pi-study/`
- [x] JSONL 结构：
  - 首行 meta：`version / id / cwd / created_at / updated_at / max_turns / message_count`
  - 后续每行一条 message：User/Assistant/ToolResult
- [x] 原子写入：写临时文件后替换，避免半截文件
- [x] 损坏/截断文件容错：只忽略尾部不完整行，中间坏行报错
- [x] 会话 ID：短 ID（如 `sess_20260817-063216-3b0d`），`--resume` 支持唯一前缀匹配

### 代码

- [x] `Agent` 增加 `history` 初始化参数，恢复历史消息到上下文
- [x] 新增 `agent_core/session/` 通用会话包：
  - `types.py`：`SessionMeta` dataclass、`SessionStore` Protocol、`SessionError`
  - `jsonl.py`：`JsonlSessionStore`（原子写、唯一前缀匹配、尾部不完整行容错、Message 序列化）
  - `__init__.py` 统一导出
- [x] `CodingSession` 接入 `session_id` / 历史恢复 / `save()`（默认使用 `JsonlSessionStore`）
- [x] CLI：
  - [x] 自动保存：每个 `prompt()` 结束后写回 JSONL
  - [x] `--resume <session_id>`：加载指定会话；工作区不匹配时拒绝恢复
  - [x] `--list-sessions`：列出当前工作区可用会话
  - [x] `--forget <id>`：删除指定会话文件
  - [x] `--list-sessions` / `--forget` 不需要 API Key，放在 `from_env()` 之前处理

### 测试（待补）

- [ ] `agent_core/session` 序列化 roundtrip 测试
- [ ] `JsonlSessionStore` save/load/list/delete 测试
- [ ] 多次保存后能加载全部历史
- [ ] 恢复后历史进入 Agent 上下文
- [ ] 唯一前缀匹配 / 歧义报错测试
- [ ] 损坏文件容错测试（尾部不完整行忽略、中间坏行报错）
- [ ] `--list-sessions` / `--forget` 测试

### 文档

- [x] 更新 README：会话存储位置、隐私说明、`--resume` 用法
- [x] 更新设计文档：`agent_core` 拥有通用会话层，`coding_agent` 只做产品组装；隐私/保留策略
- [x] 新增 `docs/adr/0001-session-persistence.md`
- [x] 更新 `docs/design/03-contracts.md`：会话存储契约

## P2：上下文压缩 / 长对话保护（已完成）

- [x] 历史超长截断 / 摘要压缩（`agent_core/compaction.py` + `CompactionSummaryMessage`）
- [x] 自动压缩（每次模型调用前） + 手动 `/compact`
- [x] 压缩策略测试（`tests/test_compaction.py`）
- [x] P2 文档与 ADR 0002
- [ ] 后续可选：大输出默认不发给模型（接入 `BashExecutionMessage.excludedFromContext`）

## TUI：mypi 终端界面（进行中）

- [x] 架构确认：`src/tui` 通用封装 + `src/tui_app` 独立应用
- [x] 引入 Textual，新增 `mypi` 命令入口
- [x] 最小骨架：消息日志 + 输入框 + `/quit` / `/compact`
- [x] 命令补全弹窗（Textual Suggester）
- [x] `/session` 会话选择弹窗：载入 / 删除
- [x] 载入会话后显示历史对话
- [x] 思考 / 工具进度状态行渲染
- [x] TUI 文档与 ADR 0003

## P3：评估与回归基准（后续）

- [ ] 建立夹具仓库任务集
- [ ] 批量运行器与 JSON 摘要
- [ ] 统计成功率 / 假成功率 / 轮次 / 工具错误

## P4：结构化 Bash 消息落地（后续）

- [ ] `BashExecutionMessage` 真正接入 Loop / 工具 / 渲染
- [ ] UI 结构化渲染
- [ ] LLM 可见性控制
- [ ] 持久化接入结构化 bash 记录

## 更后面候选

- [ ] steering / follow-up：任务中途插话纠正
- [ ] MCP / 子 Agent / 多供应商
笑笑mua~
可可爱爱mua~