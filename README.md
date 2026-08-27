# pi-study

逐层重建 Pi-Agent 核心架构的 Python 学习项目（Python 3.12 + asyncio）。

## 架构

三层单向依赖，与 `docs/design/02-architecture.md` 一致：

```text
coding_agent  知道如何做 Coding 产品（工作区、工具、提示词、CLI、渲染）
      |
      +--> agent_core  知道如何运行 Agent（状态、事件、模型/工具循环、取消）
                     |
                     +--> ai  知道如何调用模型（消息、流事件、聚合、供应商适配）
```

- `ai` 不导入任何项目包；`agent_core` 只导入 `ai`；`coding_agent` 导入两者。
- UI 不在核心堆栈中：CLI（`pi-study`）与 TUI（`mypi`）并行；TUI 由 `tui_app` 组装，通用封装在 `tui`，二者只消费事件，不窥探 Agent 状态。

## 当前状态

v0 核心 + Phase 6 已落地能力（对应 `docs/design/06-delivery-plan.md`）：

- 流式模型调用：文本增量 + `partial` 累积快照 + 工具调用解析 + `reasoning_content` 思考流
- Agent Loop：模型 → 工具 → 模型多轮循环；模型不再请求工具时结束，可选 `--max-turns` 作为安全熔断
- 事件系统：`AgentEvent` 生命周期（Agent/Turn/Message/Tool 四层嵌套）、`subscribe` 观察、同步屏障
- Coding 工具：`read` `write` `edit` `grep` `find` `ls` `bash`（工作区路径边界、命令超时/进程组终止）
- 工具输出双通道：完整展示结果与受限模型上下文结果可分离；`bash` 向模型最多提供 12,000 字符，TUI 仍可展示完整已捕获输出
- CLI：交互模式、流式渲染（思考/文本/工具/终态）、Ctrl+C 两段取消语义
- 会话持久化与恢复：JSONL 存储、自动保存、`--resume / --list-sessions / --forget`
- 命令系统：UI 无关的 `/` 命令，CLI / TUI 共用，支持 Tab 补全
- 上下文压缩：自动压缩 + `/compact` 手动压缩，安全失败不丢对话
- 工具审批：不安全工具（`write` / `edit` / `bash`）需用户输入 `y` / `n`
- Steering：运行中插话入队，下一轮注入；TUI 运行中输入即 steer，CLI 渲染 `SteeringQueued`
- TUI：`mypi` 启动 Textual 界面，Bash 命令、退出码和输出分区展示；长输出可折叠并带语法高亮

仍不做（当前阶段非目标）：MCP、子 Agent、命令沙箱、IDE/Web/RPC、会话分叉与跨会话搜索。

## 安装与运行

```bash
uv sync
```

环境变量（`.env` 会被自动加载）：

- `OPENAI_API_KEY` — 必填
- `OPENAI_MODEL` — 必填
- `OPENAI_BASE_URL` — 兼容接口地址（当前实现为必填）
- `OPENAI_CONTEXT_WINDOW` — 当前部署模型的真实总上下文窗口；配置后才启用自动压缩
- `OPENAI_MAX_OUTPUT_TOKENS` — 可选，单次回答的最大输出 token；未配置时压缩为输出预留 16,000 tokens

单次执行：

```bash
pi-study "用一句话说这个项目是什么"
```

交互模式：

```bash
pi-study                          # 工作区 = 当前目录
pi-study --workspace /path/to/repo
# 可选安全熔断：pi-study --workspace /path/to/repo --max-turns 40
```

交互说明：运行中第一次 Ctrl+C 取消当前任务并回到提示符；idle 时再按一次退出；输入 `/quit`（或 `/exit`、`/q`）退出。

内置命令：

- `/help`：显示所有命令及用法
- `/clear`：清空当前显示区，不删除会话历史
- `/model [model_id]`：查看或切换后续调用使用的模型
- `/status`：查看会话、消息、模型返回的上下文 token 与审批状态
- `/compact`：手动压缩上下文
- `/session [id|delete <id>]`：列出、载入或删除会话
- `/quit`：退出

TUI 模式：

```bash
mypi                              # 启动 TUI，工作区 = 当前目录
mypi --workspace /path/to/repo    # 指定工作区
```

TUI 使用同一组内置命令；`/session` 会打开会话选择弹窗（Enter 载入、D 删除）。运行中再输入文本会作为 steering 插入下一轮。

### 会话持久化

每次对话结束后自动保存到工作区的 `.pi-study/sessions/` 目录（已被 Git 忽略）。

```bash
# 列出当前工作区的会话
pi-study --list-sessions

# 恢复指定会话（支持唯一前缀）
pi-study --resume sess_20260817-063216-3b0d

# 删除指定会话
pi-study --forget sess_20260817-063216-3b0d
```

隐私说明：会话文件包含原始用户输入、模型回复和工具输出，属于本地数据；不承诺加密或自动清理，删除请使用 `--forget` 或手动删除 `.pi-study/`。

## 开发

```bash
# 测试（假 Provider/假 SDK，不触网络）
pytest -q

# 质量门槛
ruff check src/ tests/
ruff format --check src/ tests/
pyright
```

设计文档见 `docs/`（`design/00-07` 是实现的设计依据；`adr/0001-0005` 记录长期取舍；`archive/` 仅作学习回顾）。

## 路线

按 `docs/design/06-delivery-plan.md`，已完成：会话持久化、上下文压缩、工具审批、steering、TUI 核心。

下一步只根据真实使用中的失败选择：评测基准、工具输出内存上限、MCP / 子 Agent 等。
