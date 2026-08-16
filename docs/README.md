# 设计文档

本目录中的文档是 Python Pi 风格 Coding Agent 第一阶段实现的唯一设计依据。它们在产品代码之前编写；修改架构或范围时，必须同步更新相关文档。若修改涉及长期取舍，还必须新增 ADR。

后续项目文档默认使用中文；代码标识符、命令、协议名称和第三方技术名称保持原文。

## 阅读顺序

1. `design/00-product-scope.md`：要构建什么，以及 v0 明确不做什么
2. `design/01-technology-stack.md`：技术选型和暂不采用的方案
3. `design/02-architecture.md`：包职责和依赖规则
4. `design/03-contracts.md`：跨包通信契约
5. `design/04-boundaries.md`：运行时、文件、命令和失败边界
6. `design/05-acceptance.md`：验收场景和测试策略
7. `design/06-delivery-plan.md`：开发顺序与设计评审门槛

`archive/` 保存较早的探索性方案，仅供学习回顾，不构成当前实现要求。

