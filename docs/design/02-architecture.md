# 系统架构

## 顶层形态

产品采用 Pi 的三层堆栈。UI 不在这个堆栈中：v0 CLI 是产品适配器；未来的 `tui` 包必须保持独立。

```text
coding_agent  -- 知道如何处理编码工作
      |
      +--> agent_core -- 知道如何运行 Agent
                     |
                     +--> ai -- 知道如何调用模型

未来 tui -- 只知道如何渲染，不依赖上述三层
```

## 依赖规则

```text
ai            不导入任何本项目包
agent_core    只允许导入 ai
coding_agent  允许导入 ai 和 agent_core
tui           不导入 ai、agent_core、coding_agent
```

v0 的 CLI 入口位于 `coding_agent`，因为它负责组装 Coding 产品。CLI 消费 Agent 事件；它不能窥探 Agent 状态，也不能直接调用模型或工具。

## 包职责

| 包 | 拥有 | 不拥有 |
|---|---|---|
| `ai` | 供应商无关消息、上下文、工具 Schema、模型配置、流事件、供应商转换 | Loop、工具执行、文件、CLI、会话 |
| `agent_core` | Agent 状态、模型/工具循环、工具协议、通用 Agent 事件、取消传播 | Coding 工具、工作区、系统提示词、持久化、CLI |
| `coding_agent` | Coding 系统提示词、工作区/会话、具体工具、工具策略、CLI 渲染、未来持久化/扩展 | Provider 协议解析、通用循环机制 |
| 未来 `tui` | 终端组件、输入、布局、渲染 | Agent 语义和 Coding 工具 |

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

  coding_agent/
    cli.py
    session.py
    prompt.py
    workspace.py
    tools/read.py
    tools/write.py
    tools/edit.py
    tools/bash.py
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
- 会话序列化格式；
- 扩展 API；
- 上下文压缩策略；
- 精确的 TUI 技术；
- 与 OpenAI 兼容 Chat Completions 工具调用格式存在重大差异的供应商支持。

这些不会影响 v0 的包依赖方向。

