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

CLI 入口位于 `coding_agent`；TUI 入口位于 `tui_app`。两者都只消费 Agent 事件，不窥探 Agent 状态。

## 包职责

| 包 | 拥有 | 不拥有 |
|---|---|---|
| `ai` | 供应商无关消息、上下文、工具 Schema、模型配置、流事件、供应商转换 | Loop、工具执行、文件、CLI、会话 |
| `agent_core` | Agent 状态、模型/工具循环、工具协议、通用 Agent 事件、取消传播、通用会话层（`session/`）、上下文压缩（`compaction.py`） | Coding 工具、工作区、系统提示词、CLI |
| `coding_agent` | Coding 系统提示词、工作区/会话、具体工具、工具策略、CLI 渲染、命令系统、会话目录与 CLI 组装 | Provider 协议解析、通用循环机制、通用会话存储实现 |
| `tui` | 终端组件、输入、布局、渲染（基于 Textual 的封装） | Agent 语义和 Coding 工具 |
| `tui_app` | TUI 应用组装：把 CodingSession / CommandRegistry / AgentEvent 映射到 `tui` 组件 | 具体 TUI 框架细节（由 `tui` 封装） |

## 目标源码布局

```text
src/
  ai/
    messages.py
    context.py
    tools.py
    models.py
    events.py
    stream.py
    providers/openai_compatible.py

  agent_core/
    agent.py
    state.py
    tools.py
    events.py
    messages.py
    compaction.py
    session/
      types.py
      jsonl.py
      memory.py

  coding_agent/
    cli.py
    session.py
    prompt.py
    workspace.py
    provider.py
    commands/
      base.py
      builtin.py
    tools/read.py
    tools/write.py
    tools/edit.py
    tools/bash.py

  tui/
    app.py
    widgets.py
    theme.py
    events.py

  tui_app/
    app.py
    controller.py
    cli.py
```

这是目标地图，不要求现在一次创建所有模块。

## 运行流程

```text
用户输入
  -> CodingSession.prompt()
  -> Agent.prompt()
  -> ModelProvider.stream(ModelContext)
  -> 模型流事件
  -> 完整 AssistantMessage
  -> Agent 执行请求的 AgentTools
  -> ToolResultMessage 进入状态
  -> 重复，直至 AssistantMessage 不再包含工具调用
  -> CLI 渲染 Agent 事件
```

## 延期决策

- `ai` 是同时公开 `stream()` 与 `complete()`，还是用其中一个实现另一个；
- 会话存储从 JSONL 扩展到 SQLite 等更强大后端；
- 完整 Pi 风格 `SessionRepo / SessionStorage / Session` 分层；
- 扩展 API；
- 更精细的压缩策略（token 精确切点、增量摘要、摘要缓存）；
- TUI 组件细节（弹窗、命令补全、富渲染布局）；
- 与 OpenAI 兼容 Chat Completions 工具调用格式存在重大差异的供应商支持。

这些不会影响当前包依赖方向。

