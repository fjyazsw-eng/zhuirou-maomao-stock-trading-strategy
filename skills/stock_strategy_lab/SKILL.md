---
name: stock_strategy_lab
description: 股票AI交易助手的本地协作规则，用于指导Codex/GPT进行市场、板块、个股、执行、仓位、持仓和复盘相关任务。Use this skill when working on the stock AI assistant project, migration packages, daily market reports, closed tests, or model-governance reviews.
---

# 股票AI交易助手协作规则

## 项目定位

本系统是股票AI辅助决策系统，不是自动交易系统。它用于辅助用户判断当前市场是否适合参与、哪些板块值得观察、哪些股票是核心、空仓是否可以买、持仓是否继续拿、什么时候减仓、退出和保护利润。

必须始终强调：

- 用户做最终决策。
- 模型只做辅助，不保证盈利。
- 不自动下单，不接券商交易接口。
- 输出应提高决策质量、风控质量和复盘质量，而不是制造确定性交易指令。

## 固定分析流程

每次分析按以下顺序：

```text
天气 -> 街区 -> 班长 -> 店铺 -> 执行标签 -> 仓位 -> 持仓管理 -> 复盘
```

- 天气：市场环境，决定整体进攻、防守或观望。
- 街区：板块周期，判断启动、发酵、高潮、分歧、修复、退潮或结束。
- 班长：龙头、容量核心、趋势核心、次核心。
- 店铺：具体个股的结构、位置、量价、风险。
- 执行标签：能不能买、等不等、是否保护利润。
- 仓位：最多几成，不能盯盘时自动降级。
- 持仓管理：买了以后如何止损、止盈、保护利润。
- 复盘：阶段A/B验证，不用结果反改阶段A。

## 数据纪律

1. 阶段A只能看介入日及以前数据。
2. 阶段B只能用于事后验证。
3. 不允许未来函数。
4. 不允许阶段B反改阶段A。
5. 不允许用当前成分股倒推历史概念池。
6. 缺数据要标记，不能编造。
7. 测试要保留快照和哈希。
8. 不为了考试好看调权重。
9. 不把短窗口结果当长期胜率证明。

## 板块周期规则

主周期标签：

- STARTING：启动。
- FERMENTING：发酵。
- CLIMAX：高潮。
- DIVERGENCE：分歧。
- REPAIR：修复。
- FADING：退潮。
- ENDED：结束。
- UNKNOWN：状态不确定。

辅助交易标签：

- CLIMAX_FADING_RISK
- HIGH_LEVEL_UNSTABLE
- WAIT_FOR_CONFIRMATION
- STRUCTURAL_START
- SHORT_REPAIR
- WEAK_TO_STRONG_WATCH
- NON_MAINLINE_OPPORTUNITY
- BACKROW_RISK_SPREAD
- CORE_STILL_VALID
- CORE_BREAKING_DOWN
- SUPPORT_CONFIRMED
- SUPPORT_NOT_CONFIRMED

使用原则：

- STARTING/STRUCTURAL_START：只看核心，允许观察仓或小试错。
- FERMENTING：核心可参与，但仍受仓位上限约束。
- CLIMAX/CLIMAX_FADING_RISK：空仓不追，持仓保护利润。
- DIVERGENCE：等待承接，后排先降风险。
- FADING/ENDED：不新开仓，持仓减仓或退出。
- UNKNOWN：默认等待确认；若高位不稳定则不参与。

## 个股角色规则

角色标签：

- LEADER：情绪/强度龙头。
- CAPACITY_CORE：容量核心。
- TREND_CORE：趋势核心。
- SECONDARY_CORE：次核心。
- CATCH_UP：补涨候选。
- FOLLOWER：后排跟随。
- WEAK_STRUCTURE：弱结构。
- UNCERTAIN_ROLE：角色不确定。

原则：

- 龙头不等于涨幅第一，要看强度、持续性、辨识度和分歧时承接。
- 容量核心看成交额和资金承载，不一定涨幅最高。
- 趋势核心看10日、20日持续性和是否破位。
- 补涨不适合高潮期追。
- 后排在分歧和退潮中优先降级。
- 弱结构不作为空仓买入对象。
- 核心股也不能无脑追高。

## 执行标签规则

执行标签：

- READY_CONFIRM：条件较完整，可参与，空仓最多20%。
- READY_TRIAL：允许小仓试错，空仓最多10%。
- OBSERVE_ONLY：只观察，0%。
- WAIT_CONFIRM：等待确认，0%。
- WAIT_FOR_SUPPORT：等待承接，0%。
- WAIT_STRONG_PULLBACK：强趋势等待回踩，0%。
- OVERHEATED_NO_CHASE：高位过热不追，0%。
- HOLD_WITH_PROTECTION：持有但保护利润。
- REDUCE_RISK：降低风险，减仓。
- EXIT_LOGIC_BROKEN：逻辑失效，退出。
- BREAKDOWN_AVOID：结构破坏，规避。
- PULLBACK_WEAKENING：回调转弱，降低仓位。

执行标签必须优先于旧状态文字。板块周期、个股角色、不能盯盘状态都可以把标签降级。

## 仓位规则

保守版本：

- READY_CONFIRM：最多20%。
- READY_TRIAL：最多10%。
- OBSERVE_ONLY：0%。
- WAIT类：0%。
- OVERHEATED_NO_CHASE：0%。
- BREAKDOWN_AVOID：0%。

不能盯盘用户自动降级；没有提醒系统时进一步保守。

## 持仓管理规则

持仓标签：

- HOLD_NORMAL
- HOLD_WITH_PROTECTION
- REDUCE_PROFIT_PROTECTION
- REDUCE_RISK
- EXIT_STOP_LOSS
- EXIT_LOGIC_BROKEN
- NO_ADD_WAIT_SUPPORT
- WATCH_ONLY_HOLDING
- CORE_HOLD_BACKROW_REDUCE
- NO_WATCH_REDUCE

浮盈：

- 0%到3%：不视为安全利润。
- 3%到8%：持有但保护。
- 8%以上：必须利润保护。

浮亏：

- 0%到-3%：正常波动，不轻易补仓。
- -3%到-6%：风险观察，禁止补仓。
- 超过-6%：判断逻辑是否破坏。

## 不能盯盘用户规则

- 自动降级。
- 高潮、分歧、退潮不新开仓。
- 高波动不参与。
- 补涨和后排不追。
- 持仓要提前设置保护线。
- 无提醒系统时更保守。

## 测试规则

测试分三类：

- 小样本验证。
- 封闭样本测试。
- 2025多题实盘模拟。

后续2025测试应包含空仓买入题、持仓浮盈题、持仓浮亏题、高潮退潮题、结构性机会题、完整交易路径题。评分分为判断分和操作分，操作分优先于单纯预测涨跌。

## GPT-Codex协作规则

1. 用户提出大目标。
2. GPT生成任务包和验收标准。
3. Codex执行、测试、出报告。
4. 用户人工搬运结果。
5. GPT审查：通过 / 小修 / 返工 / 收口。
6. 每个模块控制在2到3轮。
7. 小问题记TODO，不阻塞主线。
8. 不做无限自动循环。

## 日常运行流程

日常使用先按固定顺序阅读，不直接跳到个股：

```text
大盘天气 -> 优势板块 -> 板块周期 -> 个股角色 -> 执行标签 -> 仓位 -> 持仓 -> 账户风险
```

当前日常流程MVP文件：

- `DAILY_WORKFLOW.md`：每天怎么跑、盘前/盘中/盘后怎么看。
- `REPORT_READING_GUIDE.md`：解释报告里的标签和字段。
- `scripts/check_daily_outputs.py`：检查关键日报是否生成。
- `scripts/run_daily_workflow.py`：按健康检查、总览报告、持仓建议、账户建议、输出检查的顺序串联运行。
- `reports/daily_workflow_sample.md`：日常流程示例。

日常流程边界：

- 不自动交易。
- 不自动下单。
- 不接真实交易账户。
- 不调评分权重。
- 盘中提醒未正式接入前，盘中只作为人工观察参考。

## 2025 数据搬运和测试准备

2025 阶段先做方案，再做数据搬运，再做封闭测试。不得跳过数据完整性检查直接跑策略。

当前方案文件：

- `DATA_MIGRATION_2025_PLAN.md`：2025 数据表、数据库、元数据和完整性检查方案。
- `TEST_PLAN_2025_DETAILED.md`：空仓、浮盈、浮亏、高潮退潮、结构性机会、连续路径测试设计。
- `TEST_CASE_TEMPLATE_2025.md`：统一测试题模板。
- `SCORING_STANDARD_2025.md`：100分评分标准。
- `FUTURE_LEAKAGE_GUARD_2025.md`：阶段A/B、防未来函数、快照和哈希规则。

2025 测试边界：

- 不用当前概念股名单倒推历史概念池。
- 没有历史概念成分时，只能做人工指定观察池测试。
- 阶段A只能读取 `trade_date <= as_of_date`。
- 阶段B只能做验证，不能反改阶段A。
- 缺数据必须标记“数据不足”，不能硬做。

## Token节省原则

- 能合并的问题尽量合并。
- 每轮只做一个模块。
- 不为小字段单独开一轮。
- 小细节后置。
- 报告要简明。
- GPT审查只判断通过、小修、返工或收口。
- 核心模块完成后再做大数据测试。

## 禁止事项

- 禁止自动交易。
- 禁止自动下单。
- 禁止上传token/auth/config敏感信息。
- 禁止未来函数。
- 禁止阶段B反改阶段A。
- 禁止为了测试好看调权重。
- 禁止把短窗口结果当长期胜率。
- 禁止把模型建议当确定性交易指令。

## 参考文件

需要更多细节时再读取：

- `references/module_status.md`
- `references/data_discipline.md`
- `references/execution_labels.md`
- `references/sector_cycle_labels.md`
- `references/stock_role_labels.md`
- `references/holding_management_rules.md`

## 2025 基础数据 MVP

- 数据库应放在 `D:/股票AI交易助手数据/sqlite/market_2025.sqlite`，不要放在项目 C 盘目录。
- 大缓存、临时文件、日志放在 `D:/股票AI交易助手数据/` 下。
- 轻量报告可以放在项目 `reports/data/`。
- 当前搬运脚本包括 `scripts/fetch_2025_basic_data.py`、`scripts/check_2025_data_integrity.py`、`scripts/inspect_2025_database.py`。
- 完整性检查为 `PASS_WITH_WARNINGS` 时，可以进入下一步设计，但测试报告必须明确缺失表和影响。
