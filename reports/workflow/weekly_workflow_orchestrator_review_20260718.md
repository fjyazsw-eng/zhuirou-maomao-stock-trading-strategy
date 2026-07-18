# 周度工作流编排与日内反转观察复盘 20260718

## 1. 复用的现有模块

| 阶段 | 已有实际脚本/模块 | 当前接入方式 |
|---|---|---|
| 周末现实分析 | `build_verified_market_snapshot.py`、`verified_market_snapshot.py`、市场/板块评分报告脚本 | 本轮只接收/保存结果，不重跑评分 |
| 系统性风险 | `systemic_risk_gate.py` | 作为高优先级新买入锁 |
| 人工六爻 | `hexagram_calibration.py`、`run_hexagram_calibration_tool.py` | 继续只接收人工结构化输入，只降级 |
| 前夜计划 | 现有候选、日报、选股交接脚本 | 本轮只编排首选/替补状态，不重新选股 |
| 盘中否决 | `realtime_watch_monitor.py`、东方财富只读接口语义 | 本轮只验证前夜首选/替补，不全市场重选 |
| 持仓处理 | `holding_management.py`、B 模块 Skill | 本轮只记录收盘复盘，不改卖出规则 |
| 日报/复盘 | `build_unified_stock_ai_daily_report.py`、`run_daily_workflow.py` 等 | 保留为可接入脚本，不重构 |
| 状态文件 | `current_workflow_state.json` | 统一作为编排状态 |

已有实际执行脚本：市场快照、日报/综合报告、选股研究、盘中盯盘、持仓验证、工作流状态、六爻录入。

只有状态字段的阶段：周度策略、前夜计划、收盘复盘、周五复盘、反转观察，目前以结构化状态和历史记录为主。

重复入口：存在 `run_daily_workflow.py`、`run_workflow_status.py`、`run_workflow_state_tool.py`。本轮新增 `run_workflow.py` 作为统一调度入口，不删除旧入口。

## 2. 新增或修改文件

| 文件 | 类型 | 说明 |
|---|---|---|
| `scoring_system/workflow_orchestrator.py` | 新增 | 周度编排、下一步判断、盘中动作枚举、反转观察、历史记录 |
| `scripts/run_workflow.py` | 新增 | 统一命令行入口 |
| `tests/test_workflow_orchestrator.py` | 新增 | 20 项编排和反转测试 |
| `scoring_system/workflow_state.py` | 修改 | 增加反转观察、工作流审计、每日循环阶段 |
| `reports/workflow/current_workflow_state.json` | 修改 | 补入反转观察和审计字段 |
| `reports/workflow/current_workflow_state.md` | 修改 | 重新渲染可读状态 |
| `reports/workflow/weekly_workflow_orchestrator_review_20260718.md` | 新增 | 本报告 |

## 3. 工作流编排结构

新增统一编排器：`workflow_orchestrator.py`。

核心能力：

- `build_status`：读取当前状态；
- `decide_next_command`：判断下一步；
- `complete_weekend_reality`：写入周末现实分析；
- `apply_hexagram_input`：调用人工六爻写入；
- `generate_weekly_strategy`：生成周度策略字段；
- `create_night_plan`：写入前夜首选/替补；
- `run_intraday_check`：只检查首选和替补；
- `complete_closing_review`：写入收盘复盘；
- `advance_after_closing_review`：进入下一交易日前夜或周度复盘；
- `run_reversal_check`：反转观察分支；
- `record_history`：按交易日保存审计记录。

## 4. `status` 和 `next` 行为

命令行入口：`scripts/run_workflow.py`

支持命令：

`status`、`next`、`weekend`、`hexagram`、`weekly-strategy`、`night-plan`、`intraday-check`、`closing-review`、`weekly-review`、`reversal-check`、`validate`。

实际验证：

- `status` 当前输出阶段：`WEEKEND_REALITY_PENDING`
- 当前下一步：`weekend`
- `validate` 输出：`workflow_orchestrator_valid`

`next` 映射：

| 当前阶段 | 下一步 |
|---|---|
| `WEEKEND_REALITY_PENDING` | `weekend` |
| `WEEKEND_HEXAGRAM_PENDING` | `hexagram` |
| `WEEKLY_STRATEGY_READY` | `weekly-strategy` |
| `NIGHT_PLAN_READY` | `night-plan` |
| `INTRADAY_CHECK_PENDING` | `intraday-check` |
| `INTRADAY_CHECK_COMPLETED` | `closing-review` |
| `CLOSING_REVIEW_COMPLETED` | 非周末 `night-plan`，周末 `weekly-review` |
| `WEEKLY_REVIEW_COMPLETED` | `weekend` |

## 5. 周末到周五的完整流程

标准流程：

1. 周末现实分析：写入最新完整交易日、市场状态、风险状态、重点板块、现实参与级别，进入 `WEEKEND_HEXAGRAM_PENDING`。
2. 周末人工六爻录入：一个市场、最多两个板块，运行只降级校准，进入 `WEEKLY_STRATEGY_READY`。
3. 周度策略生成：综合现实、总闸、六爻校准、板块优先级和风险窗口，保留参与级别、禁止事项、最高仓位、试错数量和失效条件。
4. 前夜计划：只保存次日首选和替补、角色、条件、数量、系统性风险与六爻窗口状态。
5. 盘中否决：只验证前夜计划，不生成第三只。
6. 收盘复盘：记录市场、板块、候选、执行、否决、总闸、六爻窗口和反转观察。
7. 周五复盘：进入周度复盘记录，下一周回到周末现实分析。

## 6. 每日循环机制

已支持交易周内循环：

`NIGHT_PLAN_READY -> INTRADAY_CHECK_PENDING -> INTRADAY_CHECK_COMPLETED -> CLOSING_REVIEW_COMPLETED -> NIGHT_PLAN_READY`

周五收盘后：

`CLOSING_REVIEW_COMPLETED -> WEEKLY_REVIEW_COMPLETED`

下一周：

`WEEKLY_REVIEW_COMPLETED -> WEEKEND_REALITY_PENDING`

历史记录通过 `reports/workflow/history/YYYYMMDD/` 保存，不用新一天覆盖前一天。

## 7. 反转观察状态

新增 `reversal_observation`：

| 状态 | 含义 |
|---|---|
| `NONE` | 无反转观察 |
| `BOTTOMING_WATCH` | 潜在低点观察，不允许新买入 |
| `REVERSAL_WATCH` | 六爻或现实提示反弹窗口，只观察 |
| `REVERSAL_PROBE_ALLOWED` | 预留状态；本轮保守方案下不由总闸状态直接进入买入 |
| `REVERSAL_CONFIRMED` | 现实确认修复，可申请解锁，但不直接买 |
| `REVERSAL_FAILED` | 反冲失败，当日不再尝试 |

透明字段：

`panic_release_detected`、`breadth_extreme_detected`、`index_stabilization_detected`、`sector_stabilization_detected`、`core_stock_support_detected`、`reversal_confirmation_count`、`reversal_data_status`。

缺数据统一保留 `UNKNOWN`，不当作通过。

## 8. 反转确认和失败条件

反转确认采用集中配置：

- 至少 5 个有效确认信号成立；
- 必须包含 `index_stabilization_detected`；
- 必须包含 `sector_stabilization_detected` 或 `core_stock_support_detected`；
- 数据状态必须 `OK/PASS`。

失败条件：

- `indexes_drop_again`
- `break_observation_low`
- `breadth_repair_failed`
- `single_stock_spike_only`
- `core_fade_without_support`
- `probe_stock_breaks_invalidation`
- 数据不可靠

失败后进入 `REVERSAL_FAILED`，维持当日新买入锁定，当日不得反复尝试。

## 9. 系统性风险与反转观察的优先级

固定优先级：

1. 数据可靠性否决；
2. 系统性风险总闸；
3. 反转观察状态；
4. 现实市场策略；
5. 六爻只降级校准；
6. 前夜候选；
7. 盘中个股否决；
8. 实际执行。

总闸开启时：

- 六爻只能触发 `REVERSAL_WATCH`；
- 现实信号充分时只能进入 `REVERSAL_CONFIRMED`；
- 盘中动作仍为 `NO_NEW_BUY_SYSTEMIC_RISK`；
- 不允许实际反转买入。

## 10. 选择的反转试错安全方案

本轮选择更保守方案：

总闸未正式解除前，不允许实际买入；`REVERSAL_PROBE_ALLOWED` 只能在总闸解除审核通过后生效。

理由：

- 不破坏第二轮系统性风险总闸；
- 不让六爻或单日反抽绕过高层禁止条件；
- 反转确认只恢复“可申请解锁/进入正常盘中检查”的资格，不直接给买入。

## 11. 历史记录结构

每日目录：

`reports/workflow/history/YYYYMMDD/`

支持文件：

- `night_plan.json`
- `intraday_check.json`
- `closing_review.json`
- `reversal_check.json`
- `execution_record.json`

周末/周度同样按日期目录保存：

- `weekend_reality.json`
- `hexagram_input.json`
- `weekly_strategy.json`
- `weekly_review.json`

记录只写结构化业务字段，不写 Token 或敏感配置。

## 12. 单元测试和全量测试

测试先行：

- 首次运行第四轮测试失败：`ModuleNotFoundError: No module named 'scoring_system.workflow_orchestrator'`
- 实现后第四轮测试：`20 passed`
- 前三轮相关测试 + 第四轮测试：`53 passed`

最终全量测试：`109 passed`。

状态校验：`workflow_state_valid`。

## 13. 五个演示场景

| 场景 | 输入摘要 | 输出 |
|---|---|---|
| A 普通震荡周 | 市场震荡、六爻中性、周度谨慎试错、盘中通过 | `BUY_PRIMARY_100` |
| B 系统性风险周 | 市场极弱、总闸开启、六爻偏强 | `NO_NEW_BUY`，新买入锁定 |
| C 六爻提示反冲但现实未确认 | 六爻进入反转窗口、次日指数继续恶化 | `REVERSAL_FAILED`，`NO_BUY_REVERSAL_UNCONFIRMED` |
| D 六爻提示反冲且现实初步确认 | 指数止跌、宽度修复、板块和核心股承接，但总闸仍锁 | `REVERSAL_CONFIRMED`，`NO_NEW_BUY_SYSTEMIC_RISK` |
| E 反冲失败 | 早盘反弹后指数/核心重新走弱 | `REVERSAL_FAILED`，当日不再尝试 |

## 14. 已知能力边界

已具备：

- 统一状态读取；
- 下一步建议；
- 周内日循环；
- 周五复盘流转；
- 前夜计划不绕过总闸；
- 盘中只检查首选和替补；
- 反转观察、确认、失败状态；
- 每日历史记录按日期落盘。

仍不具备：

- 不自动执行真实市场现实分析；
- 不自动生成候选；
- 不自动调用东方财富；
- 不自动起卦、排盘、解卦；
- 不自动解除系统性风险；
- 不自动交易；
- 不自动补仓；
- 不自动判断新闻或重大事件；
- 不做精确最低点预测。

## 15. 是否建议进入第五轮一键启动和跨 Codex 迁移

建议进入第五轮。

建议第五轮只做：

- 一键启动/检查入口；
- 运行前依赖自检；
- 历史目录和状态文件迁移；
- 跨 Codex 任务的交接摘要；
- 不改评分、不改买点、不接真实交易。
