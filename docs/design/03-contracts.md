# 跨包通信契约

本文件先定义跨包概念的含义和不变量，再决定每一个具体字段。

## 1. `ai`：模型通信

### 模型上下文

Provider 的输入是 `ModelContext`：

```text
系统提示词 + 有序消息历史 + 工具定义 + 模型选择
```

系统提示词属于模型调用配置，不是用户轮次，也不追加进对话历史。

### 可持久的 LLM 消息

`ai` 拥有能够进入后续模型上下文的供应商无关消息：

| 消息 | 创建者 | 必要关系 |
|---|---|---|
| `UserMessage` | 调用方/会话 | 开始或继续一个用户轮次 |
| `AssistantMessage` | 模型流聚合器 | 可包含文本和工具调用 |
| `ToolResultMessage` | 工具执行后的 Agent | 引用来源工具调用 ID |

内容采用块（block）而非一个过载字符串。v0 只需要文本块和工具调用块。思考块、图片块、Provider 专属元数据等到真实工作流需要时再加入。

### 工具定义与工具调用

```text
ToolDefinition：产品告诉模型可以调用什么
ToolCall：模型请求调用某个工具一次
ToolResultMessage：Agent 记录这次调用的结果
```

工具调用 ID 必不可少：单个 AssistantMessage 可能多次调用同一工具。工具结果必须通过 ID 匹配调用，不能仅按工具名称匹配。

### 模型流事件

Provider 事件是瞬时的，用于展示和聚合，不能直接当作消息历史：

```text
stream_started
text_delta
tool_call_delta
stream_completed(AssistantMessage)
stream_failed(error)
```

不变量：只有 `stream_completed` 才会产生可加入历史的完整 `AssistantMessage`。局部文本不是持久 AssistantMessage。

## 2. `agent_core`：通用 Agent 通信

### Agent 工具协议

`agent_core` 定义 `AgentTool` 协议。实现必须提供：

```text
名称、说明、JSON Schema 参数、execute(call, cancellation)
```

工具结果具有两个通道：

```text
content  -> 模型可读文本，保存为 ToolResultMessage
details  -> 产品专属结构化信息，用于日志/UI/会话
```

工具执行错误以 `is_error=True` 的结果表达，不是未捕获的 Loop 异常。模型可以据此重新发起修正后的调用。

### Agent 状态和结果

Agent 状态是可变的进程内运行状态：已配置模型、当前系统提示词、已注册工具、有序消息、运行状态、取消句柄。CLI 不可直接修改它。

一个 Agent 轮次只能有一种终态：

```text
completed      模型给出了最终 AssistantMessage
cancelled      用户或调用者停止任务
max_turns      到达配置的 Loop 上限
model_failed   Provider 未能完成调用
internal_error 不变量或实现发生意外错误
```

工具错误本身不终止轮次。

### Agent 事件

事件是公开观察机制：

```text
agent_started / agent_ended
turn_started / turn_ended
message_started / message_delta / message_completed
tool_started / tool_updated / tool_completed
```

不变量：消费者可以渲染或记录事件，但不能用事件修改 Agent 状态。这样 CLI 行为不会反过来变成 Loop 行为。

## 3. `coding_agent`：Coding 产品通信

`CodingSession` 拥有工作区、Coding Prompt、具体工具和一个 Agent 实例。它把用户输入转换为 Agent prompt，并将事件转发给 CLI。

Coding 层未来可为压缩、steering、会话说明增加自定义消息；v0 直接使用基础 LLM 消息。

## 4. 取消

取消是一种共享能力，不是错误字符串：

```text
CLI Ctrl+C -> CodingSession -> Agent -> ModelProvider / AgentTool -> process
```

第一次 Ctrl+C 取消活动轮次并使会话回到 idle；idle 状态下第二次 Ctrl+C 退出程序。已由工具写入的文件不自动回滚。

## 5. 身份与顺序

v0 仅要求以下稳定 ID：

```text
tool_call_id：连接模型工具请求及其结果
```

消息顺序代表因果顺序；事件顺序代表观察到的运行顺序。会话、运行、事件 ID 只会在持久化、重放或外部客户端出现时才需要，不能仅为了未来假设提前加入。

