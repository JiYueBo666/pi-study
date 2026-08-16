# Pi Study Agent：产品与架构

## 1. 产品定位

Pi Study Agent 是一个面向中小型仓库的 Python 编程 Agent。其核心特征是 **证据驱动的编码循环**：Agent 必须将每个声称的任务结果关联到可检查的证据——来自仓库操作和验证命令的输出。

### 主要用户

希望在 Agent 完成一个有边界的仓库任务后，仍能回答以下问题的开发者：

- Agent 推断出了什么需求？
- 它检查了哪些文件，修改了哪些文件？
- 每个重要声明由哪条命令验证？
- 哪些声明尚未验证？

### 首个可用版本

给定一个提示词和仓库路径，Agent 能够：检查文件、编辑文件、运行受控的验证命令，并以结构化的结果和证据报告结束。

### v1 明确不做

- TUI、IDE 集成、浏览器控制、MCP 和远程执行；
- 子 Agent 和多 Agent 编排；
- 长期语义记忆或向量数据库；
- 自主选择任务；
- 无工作区和超时控制的通用 shell 访问。

这些特性只有在实际任务失败需要它们时才会纳入考虑。

## 2. 改进假设

常见的编程 Agent 优化的是"生成一个看起来合理的补丁"。但看起来合理的补丁不一定是经过验证的结果：测试可能没有覆盖要求的行为，Agent 可能悄悄地缩小了需求范围，最终摘要声称的内容可能超出了命令输出实际证明的范围。

本项目验证以下假设：

> 要求对完成状态提供显式证据，可以在不显著增加成本的前提下，降低"假成功"的报告率。

### 成功指标

在固定的本地任务集上运行并记录：

- 任务成功率：验收测试通过；
- 假成功率：Agent 声称完成但验收测试失败；
- 已验证声明比例：有证据支持的事实声明 / 全部事实声明；
- 模型调用轮次中位数和 token 用量；
- 不安全操作计数：路径越界、禁止命令或超时尝试。

核心指标是假成功率。一个特性只有当它改变了上述某个指标，或修复了一类已知的失败模式，才算改进。

## 3. 已考虑过的替代方向

| 方向 | 优势 | 主要问题 | 决策 |
|---|---|---|---|
| Python 版 Pi 克隆 | 极佳的学习练习 | 没有明确的产品差异 | 借鉴其设计思想，而非功能清单 |
| 本地优先小模型 Agent | 隐私和成本优势 | 模型与运行时评估会占据早期的大部分精力 | 保持适配器开放，后续再评估 |
| 证据驱动 Agent | 可测试的可靠性改进 | 需要严格的结果定义和评估 | 选定 |

## 4. 核心运行时架构

```text
CLI / 未来 TUI
      |
      v
应用会话 (Application Session)
      |
      v
Agent Runtime -------> 事件接收器 (Event Sink)
  |       |                |
  |       |                +--> 终端输出 / JSONL 追踪
  |       v
  |    工具运行时 (Tool Runtime) ------> 工作区策略 (Workspace Policy)
  |       |
  v       v
模型适配器 (Model Adapter)   读取 / 搜索 / 编辑 / 运行
  |
OpenAI 兼容 API（后续扩展更多适配器）

Agent 结果 (Outcome)
  |
  v
证据评估器 (Evidence Evaluator) --> 最终报告
```

依赖规则比文件夹数量更重要：

- 领域类型不引入任何 SDK 或基础设施；
- Agent 运行时只认识模型和工具的协议，不依赖具体提供方；
- 工具通过明确的工作区边界操作；
- CLI 负责组装适配器和环境加载；
- 评估层消费记录下来的追踪和结果，而非内部全局状态。

## 5. 目标包结构

```text
src/pi_study/
  domain.py              # 消息、工具调用/结果、结果、证据
  events.py              # 运行时事件联合类型和事件接收器协议
  agent.py               # 模型 -> 工具 -> 模型的循环
  models/
    base.py              # 模型协议
    openai_compatible.py # 仅负责提供方适配
  tools/
    base.py              # 工具协议、schema、注册表
    workspace.py         # 规范化路径边界
    read_file.py
    search_text.py
    edit_file.py
    run_command.py
  evidence/
    collector.py
    evaluator.py
  app.py                 # 会话编排
  cli.py                 # 参数、环境、输出渲染、退出码
tests/
  unit/
  integration/
  tasks/                 # 夹具仓库及隐藏验收测试
```

不要现在就把这个目录树创建出来。只有当里程碑让某个模块的职责变得真实时，才拆出对应文件。

## 6. 领域契约

当前的 `ChatModel.complete(...) -> str` 无法表达工具调用。下一个契约应返回结构化数据：

```python
@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class AssistantTurn:
    text: str
    tool_calls: tuple[ToolCall, ...]
    stop_reason: Literal["stop", "tool_use", "length"]
```

工具执行需要结构化的结果：

```python
@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    output: str
    is_error: bool
    metadata: dict[str, object]
```

循环结束时返回明确的结果，而非最后一个字符串：

```python
@dataclass(frozen=True, slots=True)
class AgentOutcome:
    status: Literal["completed", "failed", "max_turns"]
    summary: str
    evidence: tuple[Evidence, ...]
    unverified_claims: tuple[str, ...]
```

这消除了当前的歧义：当 `max_rounds` 耗尽时，如果只返回一个看起来正常的回答，即使任务没有完成，调用方也无法区分。

## 7. 工具边界

从四个工具开始，它们足以覆盖编码循环：

| 工具 | 用途 | 必选控制项 |
|---|---|---|
| `read_file` | 检查精确内容 | 工作区路径、字节数上限 |
| `search_text` | 发现相关代码 | 结果数和文件数上限 |
| `edit_file` | 进行确定性编辑 | 工作区路径、旧文本精确匹配 |
| `run_command` | 验证行为 | 命令策略、cwd、超时、输出上限 |

所有路径通过 `Path.resolve()` 解析，且必须位于已解析的工作区根目录内。工具失败时返回 `ToolResult(is_error=True)` 给模型，而不是让整个会话崩溃。

v1 中 `run_command` 接受参数列表而非 shell 字符串。shell 语法、管道和重定向暂不纳入，直到某个任务证明有必要且设计了相应策略。

## 8. 证据模型

证据来自可观测的操作，而非模型的文本描述：

- `edit_file` 证明某个文件确实被修改了；
- 成功的 `pytest` 只证明它实际运行的测试通过了；
- 失败的命令是仍然存在问题的证据；
- 读取文件证明的是观测到的内容，而非内容本身是正确的。

每条证据记录：类型、声明、来源事件、命令或路径、退出状态和时间戳。v1 的评估器使用确定性规则，不会用第二个 LLM 来评判第一个 LLM。

## 9. 改进发现循环

不要凭空列举功能：

1. 在固定任务集上运行 Agent；
2. 保存事件、结果、补丁、命令输出和验收结果；
3. 对失败分类：发现、推理、工具使用、编辑、验证、上下文、安全或报告；
4. 选择出现最频繁或代价最高的失败类别；
5. 实现能解决它的最小机制；
6. 在同一任务集上重新运行并比较指标。

举例：多次发现失败说明需要更好的搜索；上下文溢出说明需要压缩；遗忘约束说明需要任务账本。子 Agent 只有在测量到可以受益于并行处理的独立工作时才引入。

## 10. 初始评估任务

使用带有确定性隐藏测试的小型夹具仓库：

1. 修复 Python 函数中的 off-by-one bug；
2. 添加输入验证，同时保持现有行为不变；
3. 根据仓库内的规范实现一个函数；
4. 修复一个需要修改两个文件的 bug；
5. 拒绝读取工作区外部文件的请求；
6. 处理验证命令超时的情况；
7. 在 `max_turns` 耗尽时报告结果，但不声称成功。

开发期间保留五个任务，至少两个任务在里程碑评审前不接触，以减少基准过拟合。
