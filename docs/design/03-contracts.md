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
| `CompactionSummaryMessage` | 上下文压缩器 | 替代被压缩的旧历史，进入后续上下文 |

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
名称、说明、JSON Schema 参数、execute(call, cancellation, on_progress?)
```

`on_progress` 是可选进度回调：工具在长时间执行中可把人类可读的局部输出（例如 bash 的逐行 stdout）传给它，用于 UI 实时展示。它是纯展示通道，不是消息历史的一部分；实现可以忽略它，工具结果仍以 `ToolExecutionResult` 为准。

工具结果具有两个通道：

```text
content  -> 模型可读文本，保存为 ToolResultMessage
details  -> 产品专属结构化信息，用于日志/UI/会话
```

工具执行错误以 `is_error=True` 的结果表达，不是未捕获的 Loop 异常。模型可以据此重新发起修正后的调用。

### 工具审批契约

工具执行前可经过审批钩子：

```text
BeforeToolCallHook           agent_core 的通用工具前置钩子
ToolExecutionResult | None   覆盖工具结果 | 继续执行工具
ToolBase.is_safe             coding_agent 工具的安全标记
ToolApprovalRequest          coding_agent 审批请求
ToolApprovalResult           coding_agent 内部的 (approved, intent) 二元组
```

流程：

```text
agent_core 调用 BeforeToolCallHook(tool, call)
  -> coding_agent 判断 is_safe 与 ApprovalMode
  -> 需要审批时创建 ToolApprovalRequest 和 Future
  -> coding_agent 发出 ToolApprovalRequested 事件
  -> UI 回传 y/n，解析 Future
  -> coding_agent 发出 ToolApprovalCompleted 事件
  -> 批准时 hook 返回 None；拒绝时返回 ToolExecutionResult
```

不变量：

- `agent_core` 不依赖审批类型、安全标记、审批事件或拒绝文案。
- 审批钩子由业务层（`coding_agent`）提供，`agent_core` 只解释钩子的通用返回值。
- 安全工具（`is_safe=True`）默认不触发审批，直接执行。
- 审批期间 UI 应暂停工具执行并等待用户输入 y/n。
- 取消会话时，未决审批 Future 必须被取消。

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
tool_approval_requested / tool_approval_completed
```

不变量：消费者可以渲染或记录事件，但不能用事件修改 Agent 状态。这样 CLI 行为不会反过来变成 Loop 行为。

`tool_updated` 是工具执行期间的进度事件：携带局部文本（如 bash 输出的一行），只用于展示，不进入消息历史，也不替代最终的 `tool_completed`。

### 会话存储契约

`agent_core.session.SessionStore` 是产品层调用通用会话存储的契约：

```text
save(meta, messages)              保存会话
load(session_id) -> (meta, msgs)  恢复会话
list() -> [meta]                  列出会话元数据
delete(session_id)                删除会话
resolve(id_or_prefix) -> id       唯一前缀解析
```

不变量：

- 协议层只暴露 `SessionMeta` 和 `ai.types.Message`，不暴露文件格式。
- 具体后端（如 `JsonlSessionStore`）负责 `Message <-> JSON` 转换、原子写、损坏容错。
- `save()` 自动维护 `message_count` 和 `updated_at`，调用方不需要手动同步。
- 会话文件的存储位置（如工作区 `.pi-study/sessions/`）属于产品层组装决策，不属于 `SessionStore` 协议。

### 上下文压缩契约

`agent_core.compaction` 是通用上下文压缩能力：

```text
CompactionSettings         压缩配置（阈值、保留预算、是否启用）
estimate_tokens(message)   粗略 token 估算
should_compact(messages)   是否触发自动压缩
find_cut_index(messages)   按轮次边界找切点
summarize(messages)        生成结构化摘要
compact_messages(messages) 压缩总入口（自动 / 手动 force）
```

不变量：

- 压缩结果仍是一条消息列表，其中旧历史被 `CompactionSummaryMessage` 替代，最近轮次保留原文。
- 切点只允许在 `UserMessage` 边界，禁止拆散 `AssistantMessage(tool_calls)` 与对应 `ToolResult`。
- 摘要失败时必须安全返回原消息，绝不丢对话。
- 手动 `/compact` 使用 `force=True`：有多个轮次时保留最后一个轮次，压缩之前全部历史。
- `CompactionSummaryMessage` 是通用消息，进入历史与持久化；发送给模型时转换为 `user` 消息。

## 3. `coding_agent`：Coding 产品通信

`CodingSession` 拥有工作区、Coding Prompt、具体工具和一个 Agent 实例。它把用户输入转换为 Agent prompt，并将事件转发给 CLI。

上下文压缩已由 `agent_core` 提供；Coding 层负责配置阈值、暴露 `/compact` 命令并渲染压缩事件。工具审批策略由 Coding 层实现：通过 `before_tool_call_hook` 返回是否允许，并维护待审批 Future 供 UI 回传 y/n。Coding 层未来仍可为 steering、会话说明增加自定义消息。

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
