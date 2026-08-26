# 系统架构

## 顶层形态

产品采用 Pi 的三层堆栈。UI 不在这个堆栈中：CLI 是产品适配器；TUI 通过 `tui_app` 独立组装。

```text
coding_agent  -- 知道如何处理编码工作
      |
      +--> agent_core -- 知道如何运行 Agent
                     |
                     +--> ai -- 知道如何调用模型

tui_app -- 知道如何把 Coding 会话渲染成 TUI
      |
      +--> tui -- 通用终端 UI 封装（不依赖 Agent 系统）
      +--> coding_agent
```

## 依赖规则

```text
ai            不导入任何本项目包
agent_core    只允许导入 ai
coding_agent  允许导入 ai 和 agent_core
tui           不导入 ai、agent_core、coding_agent
tui_app       允许导入 tui 和 coding_agent
```

CLI 入口位于 `coding_agent`；TUI 入口位于 `tui_app`。两者都只消费 Agent / Coding 事件，不窥探 Agent 状态。

## 包职责

| 包 | 拥有 | 不拥有 |
|---|---|---|
| `ai` | 供应商无关消息、上下文、工具 Schema、模型配置、流事件、供应商转换 | Loop、工具执行、文件、CLI、会话 |
| `agent_core` | Agent 状态、模型/工具循环、工具协议与输出双通道、通用 Agent 事件、取消传播、通用会话层（`session/`）、上下文压缩（`compaction.py`）、steering 队列、工具审批调用钩子 | Coding 工具、工作区、系统提示词、CLI、审批 UI |
| `coding_agent` | Coding 系统提示词、工作区/会话组装、具体工具、工具策略、审批策略（`is_safe` / y/n）、CLI 渲染、命令系统、会话目录、Coding 业务事件（`event.py`） | Provider 协议解析、通用循环机制、通用会话存储实现 |
| `tui` | 终端组件、输入、布局（基于 Textual 的封装） | Agent 语义和 Coding 工具 |
| `tui_app` | TUI 应用组装：把 CodingSession / CommandRegistry / AgentEvent 映射到 `tui` 组件 | 具体 TUI 框架细节（由 `tui` 封装） |

## 当前源码布局

```text
src/
  ai/
    types.py              消息、内容块、流事件、ModelConfig、ToolDefinition
    stream.py             AssistantMessage 聚合
    openai_model.py       OpenAI 兼容 Provider
    utils/
      event_stream.py
      validations.py      pydantic 参数校验

  agent_core/
    agent.py              有状态 Agent：subscribe / run / cancel / steer
    loop.py               模型 -> 工具 -> 模型主循环
    types.py              AgentTool 协议、ToolOutput / ToolExecutionResult
    events.py             AgentEvent
    compaction.py         上下文压缩
    utils.py
    session/
      types.py            SessionMeta / SessionStore Protocol
      jsonl.py            JsonlSessionStore

  coding_agent/
    cli.py                pi-study 入口
    session.py            CodingSession 产品组装
    prompt.py
    workspace.py
    provider.py           ProviderAdapter（CLI/TUI 共用）
    render.py             CLI 事件渲染
    event.py              CodingEvent（审批等）
    commands/
      base.py
      builtin.py
    tools_pacakge/        注意：历史拼写错误，真实 import 路径；重命名属破坏性改动
      tool_args.py        Pydantic 参数模型
      tool_config.py      审批模式 / 拒绝文案
      tools.py            read/write/edit/grep/find/ls/bash

  tui/
    app.py
    widgets.py
    # theme.py / events.py 预留，尚未创建

  tui_app/
    app.py
    controller.py
    screens.py
    cli.py                mypi 入口
```

这是**当前实现地图**。早期设计中的多文件拆分（如 `ai/messages.py`、`providers/`）被合并为更少模块；需要时再拆，不以文件数量为目标。

## 运行流程

```text
用户输入
  -> CodingSession.prompt()
  -> Agent.prompt() / run()
  -> ModelProvider.stream(ModelContext)
  -> 模型流事件（含 thinking_delta / text_delta / tool_call_delta）
  -> 完整 AssistantMessage
  -> Agent 经 BeforeToolCallHook（可选审批）后执行 AgentTools
  -> ToolExecutionResult.context_output 转为 ToolResult 进入状态
  -> ToolExecutionResult.display_output 作为 ToolCompleted.display 交给 UI
  -> 轮间 drain steering 队列（若有）
  -> 重复，直至 AssistantMessage 不再包含工具调用
  -> CodingSession.save() 写回 JSONL
  -> CLI / TUI 渲染 AgentEvent 与 CodingEvent
```

## 延期决策

- `ai` 是同时公开 `stream()` 与 `complete()`，还是用其中一个实现另一个；
- 会话存储从 JSONL 扩展到 SQLite 等更强大后端；
- 完整 Pi 风格 `SessionRepo / SessionStorage / Session` 分层；
- 扩展 API；
- 更精细的压缩策略（token 精确切点、增量摘要、摘要缓存）；
- 更丰富的 TUI 渲染（通用代码块、图片等）；
- 工具执行的展示输出内存上限与外部化存储；
- 将 `tools_pacakge` 重命名为 `tools`（破坏性，需统一改 import / 文档）；
- 与 OpenAI 兼容 Chat Completions 工具调用格式存在重大差异的供应商支持。

这些不会影响当前包依赖方向。
