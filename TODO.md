# TODO

按推荐优先级整理的下一步迭代事项。

## 已确定的方案决策

- P0：代码 + 测试 + 同步更新设计文档（`03-contracts` 增加 `ToolUpdated` / `on_progress`）
- P1 存储位置：工作区 `.pi-study/sessions/`
- P1 格式：JSONL
- P1 恢复方式：自动保存 + 显式 `--resume <id>`
- P1 持久化范围：只持久化 Agent 历史消息（User/Assistant/ToolResult），结构化 bash 留到 P4
- P1 CLI：额外提供 `--list-sessions` / `--forget <id>`
- P1 保存时机：每个 prompt 结束后整体保存

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

## P1：会话持久化与恢复（P0 后执行）

### 存储与格式

- [ ] 目录：`<workspace>/.pi-study/sessions/<session_id>.jsonl`
- [ ] `.gitignore` 增加 `.pi-study/`
- [ ] JSONL 结构：
  - 首行 meta：`id / workspace / model / created_at / updated_at / max_turns`
  - 后续每行一条 message：User/Assistant/ToolResult
- [ ] 原子写入：写临时文件后替换，避免半截文件
- [ ] 损坏/截断文件容错：忽略最后不完整行

### 代码

- [ ] `Agent` 增加 `history` 初始化参数，恢复历史消息到上下文
- [ ] 新增 `coding_agent/session_store.py`：
  - `save_session()` / `load_session()` / `list_sessions()` / `forget_session()`
  - 序列化/反序列化 `ai.types.Message`
- [ ] `CodingSession` 接入 `session_id` / 历史恢复 / `save()`
- [ ] CLI：
  - [ ] 自动保存：每个 `prompt()` 结束后写回 JSONL
  - [ ] `--resume <session_id>`：加载指定会话；工作区不匹配时警告
  - [ ] `--list-sessions`：列出当前工作区可用会话
  - [ ] `--forget <id>`：删除指定会话文件
- [ ] 工作区/模型不匹配时的行为明确（警告但允许 / 拒绝）

### 测试与文档

- [ ] 序列化 roundtrip 测试
- [ ] 追加保存后能加载全部历史
- [ ] 恢复后历史进入 Agent 上下文
- [ ] 损坏文件容错测试
- [ ] `--list-sessions` / `--forget` 测试
- [ ] 更新 README：会话存储位置、隐私说明、`--resume` 用法
- [ ] 更新设计文档：持久化归属与隐私/保留策略

## P2：上下文压缩 / 长对话保护（后续）

- [ ] 大输出默认不发给模型（接入 `BashExecutionMessage.excludedFromContext`）
- [ ] 历史超长截断 / 摘要压缩
- [ ] 压缩策略测试

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
- [ ] TUI：独立终端界面
- [ ] MCP / 子 Agent / 多供应商
