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
- UI 不在堆栈中：`coding_agent/render.py` 是纯事件消费者，未来可用独立 TUI 包替换。

## 当前状态

v0 完成（对应 `docs/design/06-delivery-plan.md` 的 Phase 1-5）：

- 流式模型调用：文本增量 + `partial` 累积快照 + 工具调用解析 + `reasoning_content` 思考流
- Agent Loop：模型 → 工具 → 模型多轮循环、max_turns、多轮对话历史
- 事件系统：`AgentEvent` 生命周期（Agent/Turn/Message/Tool 四层嵌套）、`subscribe` 观察、同步屏障
- Coding 工具：`read` `write` `edit` `grep` `find` `ls` `bash`（工作区路径边界、命令超时/进程组终止）
- CLI：交互模式、流式渲染（思考/文本/工具/终态）、Ctrl+C 两段取消语义
- 会话持久化与恢复：JSONL 存储、自动保存、`--resume / --list-sessions / --forget`
- 命令系统：UI 无关的 `/` 命令（当前含 `/quit`、`/compact`），Tab 补全
- 上下文压缩：自动压缩 + `/compact` 手动压缩，安全失败不丢对话
- TUI：`mypi` 启动 Textual 界面（增量迁移中，CLI 保持可用）

仍不做（当前阶段非目标）：MCP、子 Agent、命令沙箱。

## 安装与运行

```bash
uv sync
```

环境变量（`.env` 会被自动加载）：

- `OPENAI_API_KEY` — 必填
- `OPENAI_MODEL` — 必填
- `OPENAI_BASE_URL` — 兼容接口地址（当前实现为必填）

单次执行：

```bash
pi-study "用一句话说这个项目是什么"
```

交互模式：

```bash
pi-study                          # 工作区 = 当前目录
pi-study --workspace /path/to/repo --max-turns 20
```

交互说明：运行中第一次 Ctrl+C 取消当前任务并回到提示符；idle 时再按一次退出；输入 `/quit`（或 `/exit`、`/q`）退出。

TUI 模式：

```bash
mypi                              # 启动 TUI，工作区 = 当前目录
mypi --workspace /path/to/repo    # 指定工作区
```

TUI 内命令：`/quit` 退出、`/compact` 压缩上下文、`/session` 打开会话选择弹窗（Enter 载入、D 删除）。

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

设计文档见 `docs/`（`design/00-06` 是实现的唯一设计依据；`archive/` 仅作学习回顾）。

## 路线

按 `docs/design/06-delivery-plan.md`，Phase 6 的下一步能力只根据真实使用中观察到的失败来选择（持久化 / 上下文压缩 / steering / TUI / 扩展）。
