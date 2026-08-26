# 设计文档

本目录中的文档是 Python Pi 风格 Coding Agent 的设计依据。它们最初在产品代码之前编写；修改架构或范围时，必须同步更新相关文档。若修改涉及长期取舍，还必须新增 ADR。

后续项目文档默认使用中文；代码标识符、命令、协议名称和第三方技术名称保持原文。

> 说明：`design/00-product-scope.md` 最初描述的是 v0 起步范围。会话持久化、上下文压缩、TUI、工具审批、steering、工具输出双通道等已在后续 Phase / ADR 中落地。阅读范围时以 README、`06-delivery-plan` 与 ADR 的「已实现」为准，不要把早期「非目标」当成当前能力边界。

## 阅读顺序

1. `design/00-product-scope.md`：要构建什么，以及当前明确不做什么
2. `design/01-technology-stack.md`：技术选型和暂不采用的方案
3. `design/02-architecture.md`：包职责、依赖规则与当前源码布局
4. `design/03-contracts.md`：跨包通信契约
5. `design/04-boundaries.md`：运行时、文件、命令和失败边界
6. `design/05-acceptance.md`：验收场景和测试策略
7. `design/06-delivery-plan.md`：开发顺序与当前进度
8. `design/07-tui.md`：TUI 设计
9. `adr/0001-session-persistence.md`：会话持久化决策
10. `adr/0002-context-compaction.md`：上下文压缩决策
11. `adr/0003-tui-architecture.md`：TUI 架构与 Textual 选型
12. `adr/0004-tool-approval.md`：工具审批系统
13. `adr/0005-tool-output-channels.md`：工具模型上下文与界面展示输出分离

`archive/` 保存较早的探索性方案，仅供学习回顾，不构成当前实现要求。
