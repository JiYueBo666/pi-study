# 技术栈

## 选定技术

| 关注点 | 选择 | 原因 |
|---|---|---|
| 运行时 | Python 3.12+ | 当前项目基线，具备现代类型和 `asyncio` 能力 |
| 包与构建 | `uv` + Hatchling | 当前项目已使用，安装锁定快，适合可编辑开发 |
| 并发 | 标准库 `asyncio` | 模型流、命令执行和 Ctrl+C 取消需要异步控制 |
| 核心数据 | `dataclasses` + `typing` | 用最少框架耦合定义小而清晰的不可变契约 |
| 工具参数 Schema | `pydantic` | 工具参数模型校验与 JSON Schema 生成；领域消息仍以 dataclass 为主 |
| 供应商适配 | `openai` Python SDK | 首个供应商为 OpenAI 兼容接口，SDK 被隔离在 `ai` 内 |
| 环境加载 | `dotenv`（`from dotenv import load_dotenv`） | 仅在 CLI / TUI 组合边界方便加载本地 `.env` |
| CLI | `argparse` + 标准输出 | 保持轻量入口，与 TUI 并行 |
| TUI | Textual | 补全弹窗、会话选择、流式状态；封装在 `tui` / `tui_app` |
| 测试 | `pytest` | 已有依赖，适合单元和集成测试 |
| 格式化与 lint | Ruff | 快速，格式化与 lint 一体化 |
| 静态检查 | Pyright | 检查跨包协议和依赖方向 |

`pydantic` 用于工具参数边界（`ToolDefinition.from_model`、`validate_arguments`），不替代 `ai.types` 的 dataclass 消息契约。

## 暂不采用

| 方案 | 原因 |
|---|---|
| FastAPI/RPC | 当前没有外部客户端 |
| 数据库（SQLite 等） | P1 已用 JSONL；更强查询/并发需求出现前推迟 |
| LangChain/LangGraph | 会隐藏当前要学习的 Loop 与消息契约 |
| MCP 框架 | Pi 将其作为可选能力，当前没有工作流需要 |
| 独立 worker/队列 | 单个本地交互会话不需要 |
| 语言解析器/AST 框架 | 先通过文件和命令实现语言无关 |

## 依赖策略

- 领域类型、路径、进程控制、序列化、取消优先采用标准库。
- 第三方库必须被隔离在拥有它的包边界内。
- Provider SDK 对象、HTTP 响应对象、`subprocess` 对象不得跨越所属边界。
- 凭据只在 CLI/TUI 配置组合层读取，不得出现在模型或领域对象中，也不得显示。

## 运行时依赖（与 `pyproject.toml` 对齐）

```text
openai
pydantic
dotenv
textual
```

开发依赖：

```text
pytest
ruff
pyright
```

在实现第二个供应商之前，供应商 SDK 仍只保留 OpenAI 兼容适配。