# TUI 设计

## 目标

在保留现有 CLI 的前提下，为 pi-study 提供独立的 Textual TUI 界面。TUI 与 CLI 共享同一套 `CodingSession / CommandRegistry / AgentEvent`，但 UI 实现完全分离。

## 分层

```text
src/tui/                    通用 Textual 封装层
  app.py                    TuiApp 基类
  widgets.py                CommandInput / MessageLog
  theme.py                  主题（预留）

src/tui_app/                pi-study TUI 应用
  app.py                    MyPiApp：主布局 + Agent 事件渲染
  controller.py             TuiController：桥接 CodingSession / CommandRegistry / SessionStore
  screens.py                SessionPickerScreen 等弹窗
  cli.py                    mypi 入口
```

依赖规则：

```text
tui          不导入 ai / agent_core / coding_agent
tui_app      导入 tui + coding_agent（以及传递依赖）
coding_agent 不导入 tui；CLI 完全不变
```

## 当前能力

- 消息日志区 + 输入框
- `/` 命令补全弹窗（Textual Suggester）
- `/session` 打开会话选择弹窗：
  - Enter 载入会话
  - D 删除会话
  - Esc 关闭
- 载入会话后显示完整历史对话
- 思考流（`ThinkingDeltaEvent`）与工具进度（`ToolUpdated`）实时显示在状态行
- `/quit` 退出、`/compact` 手动压缩

## 与 CLI 的关系

| 能力 | CLI | TUI |
|---|---|---|
| 会话 | `--resume / --list-sessions / --forget` | `/session` 弹窗 |
| 命令 | 同一 `CommandRegistry` | 同一 `CommandRegistry` |
| Agent 事件 | `TerminalRenderer` | `MyPiApp._on_agent_event` |
| 启动 | `pi-study` | `mypi` |

## 增量迁移计划

- [x] 最小骨架：日志 + 输入 + `/quit` + `/compact`
- [x] 命令补全弹窗
- [x] `/session` 会话选择弹窗（载入/删除）
- [x] 思考流与工具进度状态行
- [ ] 会话恢复后的模型切换 / 更多命令
- [ ] 富渲染（工具输出、代码块、图片）
