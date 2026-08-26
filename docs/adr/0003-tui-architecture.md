# 0003：TUI 架构与 Textual 选型

状态：accepted

## 背景

CLI 已经可用，但终端输出受限，需要更丰富的交互（补全弹窗、会话选择、流式状态）。设计文档 Phase 6 将“独立 TUI 包”列为候选能力。同时要求不破坏现有 CLI，TUI 不依赖 CLI，独立于 Agent 系统外。

## 决策

- 引入 Textual 作为 TUI 框架。
- 新增两个包：
  - `src/tui`：通用 Textual 封装层，不依赖 `ai / agent_core / coding_agent`。
  - `src/tui_app`：pi-study 的 TUI 应用，依赖 `tui` 和 `coding_agent`。
- 新增启动命令 `mypi`，CLI `pi-study` 保持不变。
- 将 `ProviderAdapter` 从 `cli.py` 抽到 `coding_agent/provider.py`，CLI 与 TUI 共用。
- 命令系统继续使用同一个 `CommandRegistry`；`/session` 通过 `CommandResult.data` 返回结构化会话数据，TUI 据此打开弹窗。
- 会话切换由 `TuiController` 负责：替换 `CodingSession`、重新订阅 Agent 事件、刷新历史渲染。
- `ToolCompleted.display` 是 TUI 的工具结果输入：Bash 用结构化 `details` 分别显示命令、退出码和输出；长输出默认折叠。TUI 不从 Agent 私有状态读取这些数据。

## 后果

- TUI 与 CLI 共享业务层，避免重复实现。
- `tui` 层保持通用，未来更换 TUI 框架只影响 `src/tui`。
- 引入第三方依赖 `textual`，增加安装体积。
- TUI 的会话弹窗、补全、流式渲染需要持续迭代。

## 考虑过的替代方案

- **prompt_toolkit**：擅长命令行补全，但完整聊天 TUI 布局不如 Textual 直观，拒绝。
- **直接在 `coding_agent` 里实现 TUI**：会让产品层依赖 TUI 框架，破坏“UI 不在堆栈内”的原则，拒绝。
- **让 TUI 依赖 CLI**：会形成 UI 到 UI 的耦合，拒绝。
