# 0004：工具审批系统

状态：accepted

## 背景

部分工具（如 `bash`）可以访问工作区外文件、网络或用户凭据。为了让用户在危险操作前有明确决策点，需要引入工具审批机制，同时保持 `agent_core` 通用、不依赖 Coding 产品。

## 决策

- `agent_core` 定义：
  - `BeforeToolCallHook`：由业务层注入的通用工具前置钩子
  - hook 返回 `None` 时执行工具，返回 `ToolExecutionResult` 时跳过工具并使用该结果
- `coding_agent` 拥有完整审批业务：
  - `ToolBase.is_safe` 定义 Coding 工具的安全性
  - `ToolApprovalRequest` / `ToolApprovalResult` 和审批事件均定义在 Coding 层
  - `ApprovalMode.ASK`：不安全工具等待用户 y/n
  - `ApprovalMode.AutoAccept`：自动放行
  - `RejectResponse` 与 `custom.toml` 定义拒绝后的返回文本
  - `resolve_tool_approval(request_id, approved)` 用于 UI 回传决策
- TUI 对接：
  - 收到 `ToolApprovalRequested` 后显示高亮审批框
  - 输入 `y` / `n` 调用 `resolve_tool_approval`
  - 决策后重新进入执行流程

## 后果

- 危险工具调用前有明确人工确认点。
- `agent_core` 保持通用：替换 Coding 业务时无需修改 loop。
- UI（CLI/TUI）可以通过事件感知审批状态。
- 取消会话时必须取消未决审批 Future，避免悬挂。

## 考虑过的替代方案

- **全部工具自动执行**：危险操作无确认，不安全，拒绝。
- **全部不安全工具直接拒绝**：过于保守，无法完成需要 bash 的真实任务，拒绝。
- **只在 CLI 里拦截**：TUI 无法复用，且核心层不可见，拒绝。
