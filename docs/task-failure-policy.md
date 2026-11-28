# 任务失败间隔、有界预算与循环治理约定

GUI 的「执行任务失败后设定」（`scheduler.failure_interval`）决定一次任务失败后的下次重试时刻；任务内部与公共辅助层的有界预算则保证失控循环能够在确定时间内退出并交回调度器。两者共同构成 OAS 的防卡死与恢复基线。

## 1. 失败调度与检查点隔离

- **业务失败间隔守恒**：任务真实失败时，从失败结束时刻起按该任务的 `scheduler.failure_interval`（`server=False`）计算 `retry_at`，不再被服务器刷新时间、旧任务启动时间或固定短间隔覆盖。
- **未完成任务检查点（`TaskCompletionGate`）**：在 `log/task_retry/<config>.json` 中持久化未完成业务任务的 `not_before`。配置热重载、后台重启或其他任务触发均不会提前已推迟的重试时间；检查点仅在该任务完成或被用户在配置中关闭时释放。
- **环境恢复隔离**：`GotoMain` 采用独立的 5 分钟短退避周期；`Restart` 与 `GotoMain` 的重试下限记录在 `recovery_not_before` 中，绝不覆盖当前固定的未完成业务任务名称。
- **防风控与多实例协同**：`TaskCompletionGate` 选出候选任务后，仍依次遵守 `AntiBanGuard` 作息唤醒窗口与 `InstanceGuard` 跨进程排队令牌。

## 2. 全局与公共层流程上限

- **任务流守卫（`TaskFlowGuard`）**：所有经 `Device.screenshot()` 的 `/tasks/` 调用栈受双层时间上限保护——默认无进展上限 `420s`、硬上限 `1800s`。普通点击、动画或清空检测记录均不续期；仅经确认的页面进展可续期无进展预算，仅战斗计数推进可重置硬上限（已配置更长 `battle_timeout` 或等待窗口的任务自动按配置放宽）。调试模式调用 `disable_stuck_detection()` 时同步暂停该守卫。
- **导航累计有界预算（`_NavigationBudget`）**：`GameUi.goto_page` 默认限制累计 `max_steps=64`、`total_timeout=180s`、`max_recoveries=2`、`max_polls=256`；页面来回切换与未知页恢复均**不重置**总预算。
- **公共等待与弹窗动作有界化（`BaseTask`）**：
  - `wait_until_appear`、`wait_until_disappear`、`wait_animate_stable` 未显式传入超时时默认受 `_default_wait_timeout()`（至少 `420s`，不短于配置的战斗超时）约束，超时抛出 `TaskRecoveryFailed`；显式传入超时参数时保持返回 `False` 的布尔语义。
  - `ui_reward_appear_click` 与 `ui_get_reward` 通过 `click_confirm_once` 与单次领取源触发避免对领奖源按钮重复连点。
  - `_burst`（协战突发弹窗）限制在 `12s` 内单次点击并通过连续两帧新截图验证弹窗消失或发送方横幅替换，且在 `finally` 中无条件恢复调用方的 `detect_record`。
  - `ui_click`、`ui_clicks`、`ui_click_until_disappear`、`ui_click_until_smt_disappear`、`ui_click_multi_scale` 均采用有限时间窗 + `_ui_verify` 双新鲜帧确认。
- **点击响应校验与确认重试**：`click_verification` 在点击前后比对局部像素，拦截对无响应控件的盲目连点；`click_confirm_once` 仅允许非消费类确认/关闭按钮在连续两帧上下文未变时消耗唯一许可重试一次。
- **多尺度模板搜索网格上限（`module/image/scales.py` & `RuleImage.match_multi_scale`）**：本地与图像服务统一限制单次多尺度网格最多 `2048` 个采样点，拒绝非有限边界与无法推进浮点数的极小步长。

## 3. 静态循环盘点与回归门禁

仓库提供可复现的 AST 静态盘点脚本 `dev_tools/audit_task_loops.py`，扫描全部 `tasks/`、`module/` 与 `script.py` 中的 `while` 循环及 `success=False` 调用，并生成 [task-loop-inventory.md](task-loop-inventory.md) 清单。表中的“无显式终止候选”仅表示局部语法未检出显式计时器/计数器退出分支（运行时仍受外层 `TaskFlowGuard` 与 `_NavigationBudget` 兜底），用于指导后续逐任务精细化改造。

常用命令：

```powershell
# 更新 Markdown 循环盘点表
python -B dev_tools/audit_task_loops.py . --md-only docs/task-loop-inventory.md

# 输出完整 JSON + Markdown 盘点产物
python -B dev_tools/audit_task_loops.py . log/task-loop-inventory.json

# CI 门禁检查（校验全库零语法解析错误且 tasks/base_task.py 零无界 while 循环）
python -B dev_tools/audit_task_loops.py . --check
```
