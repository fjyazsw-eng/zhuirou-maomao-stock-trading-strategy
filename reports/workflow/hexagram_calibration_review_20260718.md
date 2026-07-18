# 人工六爻输入与只降级校准复盘 20260718

## 1. 复用的现有结构

| 结构 | 复用方式 |
|---|---|
| `workflow_state.py::hexagram_manual_input` | 继续作为六爻人工输入主区块，保留 `DOWNGRADE_ONLY` |
| `workflow_state.py::weekly_strategy.participation_level` | 作为现实参与级别和最终校准结果落点 |
| `workflow_state.py` 阶段流转 | 支持 `WEEKEND_HEXAGRAM_PENDING -> WEEKLY_STRATEGY_READY` |
| `systemic_risk_gate.py` | 读取 `new_buy_locked`，总闸开启时六爻不得解除 |
| `reports/workflow/current_workflow_state.json` | 继续作为统一工作流状态文件 |
| 三模块 Skill | 复用极弱不买、弱市最多一只、盘中否决、100股、只读不交易边界 |
| 旧六爻模板 | 复用“六爻只作现实校准、不得迎合卦象、现实数据优先”的原则 |

潜在冲突已处理：

- 旧研究室文档提到六爻解释，但本轮实现只接收人工整理后的结构化结论，不自动起卦、不排盘、不解卦。
- 现有状态原本允许覆盖六爻字段，本轮新增“同一有效问题和时间范围不得重复覆盖”的检查。
- 六爻偏强可能被误用为升级信号，本轮固定为 `DOWNGRADE_ONLY`，没有任何升级路径。

缺失项已补：

- 人工六爻输入对象；
- 有效期与失效状态；
- 只降级映射；
- 风险窗口/有利窗口处理；
- 命令行人工录入入口；
- 单元测试和示例验证。

## 2. 新增或修改文件

| 文件 | 类型 | 说明 |
|---|---|---|
| `scoring_system/hexagram_calibration.py` | 新增 | 人工六爻输入、校验、只降级校准、写入状态、标记失效 |
| `scripts/run_hexagram_calibration_tool.py` | 新增 | 最小命令行入口 |
| `tests/test_hexagram_calibration.py` | 新增 | 覆盖 13 项六爻校准行为 |
| `scoring_system/workflow_state.py` | 修改 | 扩展六爻字段、校验、Markdown 展示 |
| `reports/workflow/current_workflow_state.json` | 修改 | 补入六爻校准结果字段 |
| `reports/workflow/current_workflow_state.md` | 修改 | 重新渲染可读状态 |
| `reports/workflow/hexagram_calibration_review_20260718.md` | 新增 | 本报告 |

## 3. 人工六爻输入结构

字段：

- `input_time`
- `question`
- `target_type`: `MARKET / SECTOR`
- `target_name`
- `observation_start_date`
- `observation_end_date`
- `hexagram_direction`: `POSITIVE / NEUTRAL / CAUTIOUS / NEGATIVE / HIGH_RISK`
- `phase_pattern`: `STABLE_STRONG / STRONG_THEN_WEAK / WEAK_THEN_STABLE / VOLATILE / REVERSAL_RISK / UNKNOWN`
- `risk_windows`
- `favorable_windows`
- `confidence_level`: `LOW / MEDIUM / HIGH`
- `analyst_summary`
- `raw_notes`
- `validity_status`: `VALID / EXPIRED / INVALIDATED`
- `invalidation_reason`
- `source`: 固定 `MANUAL`

工作流支持：

- 1 个市场六爻结果；
- 最多 2 个有效板块六爻结果；
- 风险窗口和有利窗口聚合到 `timing_windows`；
- 录入来源固定为人工；
- 规则固定为 `DOWNGRADE_ONLY`。

## 4. 只降级不升级映射

| 现实参与级别 | 六爻方向 | 校准结果 |
|---|---|---|
| `NO_NEW_BUY` | 任意方向 | `NO_NEW_BUY` |
| `CAUTIOUS_TRIAL` | `POSITIVE / NEUTRAL` | `CAUTIOUS_TRIAL` |
| `CAUTIOUS_TRIAL` | `CAUTIOUS / NEGATIVE / HIGH_RISK` | `NO_NEW_BUY` |
| `NORMAL_TRIAL` | `POSITIVE / NEUTRAL` | `NORMAL_TRIAL` |
| `NORMAL_TRIAL` | `CAUTIOUS` | `CAUTIOUS_TRIAL` |
| `NORMAL_TRIAL` | `NEGATIVE / HIGH_RISK` | `NO_NEW_BUY` |

硬约束：

- 六爻不得把 `NO_NEW_BUY` 升级；
- 六爻不得把 `CAUTIOUS_TRIAL` 升级为 `NORMAL_TRIAL`；
- 六爻不得解除系统性风险总闸；
- 六爻不得跳过盘中否决；
- 六爻不得把观察股升级成推荐股。

## 5. 风险窗口处理

已支持：

- 当前日期落入 `risk_windows` 时，只允许降级；
- `NORMAL_TRIAL` 在风险窗口内降为 `CAUTIOUS_TRIAL`；
- `CAUTIOUS_TRIAL` 在风险窗口内降为 `NO_NEW_BUY`；
- `NO_NEW_BUY` 保持禁止新买入；
- 风险窗口不会改变持仓卖出规则。

有利窗口处理：

- 只记录为 `favorable_windows`；
- 不自动产生买入建议；
- 不改变首选/替补；
- 不跳过系统性风险总闸；
- 不跳过盘中否决。

## 6. 有效期与失效规则

已支持：

- 超过 `observation_end_date` 后，校准时视为 `EXPIRED`；
- `validity_status = INVALIDATED` 后不参与当前策略；
- 人工主动标记失效需要 `invalidation_reason`；
- 同一问题、同一对象、同一时间范围内，有效结果不得重复覆盖；
- 原结果明确失效后，允许重新录入。

本轮未自动判断，但结构已可记录：

- 用户由空仓变为持仓；
- 交易目标改变；
- 标的或板块发生实质变化；
- 出现改变市场结构或公司逻辑的重大事件；
- 原问题已不成立。

普通盘中涨跌不会自动让六爻失效。

## 7. 与系统性风险总闸的优先级

固定优先级：

1. 数据可靠性否决；
2. 系统性风险总闸；
3. 现实市场策略；
4. 六爻只降级校准；
5. 前夜首选和替补；
6. 盘中否决；
7. 实际执行。

若 `systemic_risk_gate.new_buy_locked = true` 或 `daily_execution_state.new_buy_locked = true`：

- 校准结果强制为 `NO_NEW_BUY`；
- 输出 `blocked_by_systemic_risk = true`；
- 保留 `final_intraday_action = NO_NEW_BUY_SYSTEMIC_RISK`；
- 六爻偏强或有利窗口均不能解除。

## 8. 命令行或人工录入方式

入口：

`scripts/run_hexagram_calibration_tool.py`

可用命令：

| 命令 | 用途 |
|---|---|
| `template` | 创建市场或板块人工输入模板 |
| `validate` | 校验人工 JSON 输入 |
| `preview` | 查看校准前后策略，不写入状态 |
| `write` | 写入 `current_workflow_state.json` 并生成 Markdown |
| `invalidate` | 标记已有有效结果失效 |

已实际验证模板入口：

```text
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts\run_hexagram_calibration_tool.py template --target-type MARKET --target-name 全市场 --question 下周A股整体参与风险如何 --start-date 20260720 --end-date 20260724
```

输出为结构化 JSON 模板，默认 `source = MANUAL`，默认 `hexagram_direction = NEUTRAL`，默认 `phase_pattern = UNKNOWN`。

## 9. 单元测试与全量测试结果

测试先行：

- 首次运行新增测试失败：`ModuleNotFoundError: No module named 'scoring_system.hexagram_calibration'`
- 实现后六爻测试 + 工作流状态 + 系统性风险测试：`33 passed`
- 全量测试：`89 passed`
- 当前工作流状态校验：`workflow_state_valid`

覆盖项：

| 要求 | 状态 |
|---|---|
| 现实正常 + 六爻偏强，保持正常 | 已覆盖 |
| 现实正常 + 六爻谨慎，降为谨慎 | 已覆盖 |
| 现实正常 + 六爻高风险，禁止买入 | 已覆盖 |
| 现实谨慎 + 六爻偏强，不得升级 | 已覆盖 |
| 现实禁止 + 六爻偏强，仍禁止 | 已覆盖 |
| 系统性风险开启 + 六爻偏强，仍禁止 | 已覆盖 |
| 六爻风险窗口只降级 | 已覆盖 |
| 六爻有利窗口不得自动生成买入 | 已覆盖 |
| 六爻过期后不参与当前策略 | 已覆盖 |
| 六爻失效后不参与当前策略 | 已覆盖 |
| 同一有效问题不得重复覆盖 | 已覆盖 |
| 工作流阶段合法转换 | 已覆盖 |
| 原有全部测试继续通过 | 已覆盖，`89 passed` |

## 10. 三个示例结果

| 示例 | 输入 | 输出 |
|---|---|---|
| A | 现实 `NORMAL_TRIAL`，六爻 `CAUTIOUS` | `CAUTIOUS_TRIAL`，`downgrade_applied=true`，结论：降为谨慎试错 |
| B | 现实 `NO_NEW_BUY`，六爻 `POSITIVE` | `NO_NEW_BUY`，不得升级，结论：禁止新买入 |
| C | 系统性风险总闸开启，六爻 `POSITIVE` 且有利窗口 | `NO_NEW_BUY`，`blocked_by_systemic_risk=true`，`final_intraday_action=NO_NEW_BUY_SYSTEMIC_RISK` |

## 11. 能力边界

已具备：

- 接收人工六爻结构化结论；
- 校验字段、枚举、人工来源；
- 最多两个有效板块结果；
- 同一有效问题防覆盖；
- 过期和失效不参与校准；
- 只降级不升级；
- 总闸优先；
- 命令行模板、校验、预览、写入、失效入口。

不具备：

- 不自动起卦；
- 不自动排盘；
- 不自动解卦；
- 不自动预测涨跌；
- 不将六爻作为加分项；
- 不生成股票推荐；
- 不修改评分、买点、仓位或持仓卖出规则；
- 不自动交易；
- 不自动判断重大事件导致六爻失效，只提供字段和人工失效入口。

## 12. 是否建议进入第四轮周度工作流编排

建议进入第四轮。

理由：

- 当前状态文件已能连续承接现实分析、系统性风险总闸、人工六爻校准、前夜计划、盘中否决和复盘字段；
- 总闸和六爻优先级已经固定；
- 下一轮可以只做“周末到周五的编排入口和报告落盘”，不需要改评分和交易规则。

第四轮建议边界：

- 编排现有模块，不重写评分；
- 固化周末、前夜、盘中、收盘、周五复盘入口；
- 保存每周结果用于后续统计；
- 继续保持六爻只降级、不升级。
