# 系统性风险总闸搭建复盘 20260718

## 1. 复用了哪些现有能力

| 现有能力 | 复用方式 | 当前缺口 |
|---|---|---|
| `verified_market_snapshot.py::market_state` | 复用 `强 / 震荡 / 弱 / 极弱 / 待确认` 日线市场状态；缺状态时用核心指数均值和上涨占比回算 | 原模块只给市场状态，不给系统性风险对象 |
| `verified_market_snapshot.py` 已验证快照 | 复用 `trade_date`、`data_source`、`snapshot_status`、`market.state`、`market.breadth.up_ratio`、`market.core_indexes` | 历史截面需要有完整快照或本地日线/指数数据 |
| `realtime_watch_monitor.py` | 复用 `DATA_STALE`、`DATA_ERROR`、`market_ok`、盘中数据新鲜度语义 | 未改动原盘中个股判断；总闸只读取同类状态语义 |
| `sector_cycle_classifier.py` | 复用 `FADING`、`CORE_BREAKING_DOWN`、`BACKROW_RISK_SPREAD` 等作为上游可传入信号的语义来源 | 本轮不新增自动板块扫描，只接收上游组合信号 |
| `leader_score.py` | 复用龙头/容量核心/趋势核心评分结果作为未来核心股同步走弱输入来源 | 本轮不改评分，也不自动重跑龙头评分 |
| `stock_role_classifier.py` | 复用 `LEADER / CAPACITY_CORE / TREND_CORE / WEAK_STRUCTURE / FOLLOWER` 等角色语义 | 本轮不改角色分类规则 |
| `workflow_state.py` | 复用当前工作流状态文件，新增 `systemic_risk_gate` 区块并与 `daily_execution_state.new_buy_locked` 同步 | 不做自动定时，不接入真实交易 |
| 三模块 Skill 和 `config/stock_ai_rule_profiles.json` | 复用“极弱不推荐新买入”“弱市最多一只”“实时数据不足取消新买入”“默认100股”规则语义 | Skill 和配置未修改 |

## 2. 新增或修改了哪些文件

| 文件 | 类型 | 说明 |
|---|---|---|
| `scoring_system/systemic_risk_gate.py` | 新增 | 统一系统性风险对象、硬否决、组合信号、工作流锁定/解锁入口 |
| `scoring_system/workflow_state.py` | 修改 | 新增 `systemic_risk_gate` 状态区块、校验和 Markdown 渲染 |
| `tests/test_systemic_risk_gate.py` | 新增 | 覆盖总闸、锁定、解锁、跳过个股检查、持仓不强制卖出 |
| `reports/workflow/current_workflow_state.json` | 修改 | 补入总闸状态字段 |
| `reports/workflow/current_workflow_state.md` | 修改 | 重新渲染人类可读总闸状态 |
| `reports/workflow/systemic_risk_gate_review_20260718.md` | 新增 | 本报告 |

## 3. 系统性风险字段

新增风险对象字段：

| 字段 | 含义 |
|---|---|
| `assessment_time` | 本次评估时间 |
| `data_trade_date` | 使用的数据交易日 |
| `data_source` | 数据来源 |
| `market_state` | 正式市场状态 |
| `risk_level` | `NORMAL / CAUTION / HIGH / SYSTEMIC` |
| `hard_veto_triggered` | 是否触发硬否决 |
| `hard_veto_reasons` | 硬否决原因 |
| `escalation_score` | 有效恶化信号数量 |
| `escalation_signals` | 每个组合信号的 `TRUE / FALSE / UNKNOWN` 状态 |
| `new_buy_locked` | 是否禁止新买入 |
| `lock_reason` | 锁定原因 |
| `lock_scope` | 当前固定为 `NEW_BUY_ONLY`，不处理持仓卖出 |
| `assessment_details` | 指数、宽度、跳过个股检查等细节 |
| `data_status` | 数据状态和可靠性 |

工作流状态新增字段：

`systemic_risk_status`、`systemic_risk_level`、`systemic_risk_checked_at`、`systemic_risk_reasons`、`new_buy_locked`、`new_buy_lock_date`、`new_buy_lock_reason`、`new_buy_unlock_pending`、`new_buy_lock_history`、`assessment_details`。

## 4. 硬否决规则

第一版已支持：

| 硬否决 | 当前实现 |
|---|---|
| 正式市场状态为 `极弱` | 触发 `MARKET_STATE_EXTREME_WEAK` |
| 三大核心指数同步明显下跌 | 三大指数均 `<= -1.5%`，触发 `THREE_CORE_INDEXES_DROP_TOGETHER`；该阈值复用盘中模块里“大盘明显下跌”的保守语义 |
| 全市场上涨占比低于极弱阈值 | `up_ratio <= 0.20`，触发 `MARKET_BREADTH_EXTREME_WEAK`，阈值来自 `market_state` |
| 关键数据缺失、过期或不可靠 | `snapshot_status/data_status` 非 `PASS/OK` 或缺 `market`，触发 `DATA_UNRELIABLE` |
| 工作流已记录当日锁定 | 同一 `data_trade_date` 已锁，触发 `WORKFLOW_ALREADY_LOCKED_TODAY` |

硬否决结果统一为：

- `risk_level = SYSTEMIC`
- `new_buy_locked = true`
- `lock_scope = NEW_BUY_ONLY`
- 首选和替补挂起，不继续个股层买入检查
- 盘中最终动作为 `NO_NEW_BUY_SYSTEMIC_RISK`
- 持仓复盘内容保持原样，不强制卖出

## 5. 风险扩大组合规则

集中配置在 `SYSTEMIC_RISK_CONFIG`：

| 参数 | 当前值 |
|---|---:|
| `extreme_weak_up_ratio` | `0.20` |
| `core_index_sync_drop_pct` | `-1.50` |
| `index_worsening_delta_pct` | `-0.20` |
| `breadth_fast_decline_delta` | `-0.10` |
| `high_signal_count` | `3` |
| `systemic_signal_count` | `4` |
| `systemic_pair` | `index_worsening + strong_sector_selloff` |

组合信号：

| 信号 | 状态处理 |
|---|---|
| `index_worsening` | 可由前后观察点自动推导；缺前值为 `UNKNOWN` |
| `strong_sector_selloff` | 接收上游板块周期/人工结构信号；缺失为 `UNKNOWN` |
| `core_stocks_breakdown` | 接收上游核心股破位信号；缺失为 `UNKNOWN` |
| `role_stack_weakening` | 接收龙头/中军/后排同步走弱信号；缺失为 `UNKNOWN` |
| `breadth_fast_decline` | 可由前后上涨占比自动推导；缺前值为 `UNKNOWN` |
| `defensive_divergence_with_market_risk` | 接收防御抗跌但整体风险扩大信号；缺失为 `UNKNOWN` |

判定：

- 0 个有效恶化信号：`NORMAL`
- 1-2 个有效恶化信号：`CAUTION`
- 3 个有效恶化信号：`HIGH`
- 4 个及以上有效恶化信号：`SYSTEMIC`
- 3 个信号且包含 `index_worsening` 和 `strong_sector_selloff`：`SYSTEMIC`
- `UNKNOWN` 不计入成立信号

## 6. 当日锁定与解锁机制

已支持：

- 当日一旦锁定，同一交易日再次评估不会自动解除；
- 同日重复检查只会维持锁定；
- 锁定原因写入 `new_buy_lock_reason`，历史原因进入 `new_buy_lock_history`；
- 解锁入口为 `release_new_buy_lock_if_recovered`，只允许下一交易日或之后的完整复核执行；
- 解锁条件要求：数据可靠、市场不再 `极弱`、风险等级降至 `NORMAL/CAUTION`；
- 解锁后只恢复到 `INTRADAY_CHECK_PENDING`，不直接生成买入动作。

未做：

- 不做盘中自动解锁；
- 不自动调用 Tushare 或东方财富；
- 不自动生成新候选；
- 不改变持仓卖出规则。

## 7. 与工作流状态如何衔接

锁定时：

- `systemic_risk_gate.systemic_risk_status = LOCKED`
- `systemic_risk_gate.systemic_risk_level = SYSTEMIC`
- `systemic_risk_gate.new_buy_locked = true`
- `daily_execution_state.new_buy_locked = true`
- `night_plan.plan_status = SUSPENDED_BY_SYSTEMIC_RISK`
- `primary_candidate.status = SUSPENDED_BY_SYSTEMIC_RISK`
- `backup_candidate.status = SUSPENDED_BY_SYSTEMIC_RISK`
- `intraday_veto_result.market_veto = true`
- `intraday_veto_result.final_intraday_action = NO_NEW_BUY_SYSTEMIC_RISK`
- `assessment_details.candidate_checks_skipped = true`

未锁定时：

- 原有盘中否决逻辑保持不变；
- 总闸仅输出风险对象，不替代候选生成、评分和个股买点判断。

## 8. 单元测试和全量测试结果

测试先行验证：

- 新测试首次运行失败：`ModuleNotFoundError: No module named 'scoring_system.systemic_risk_gate'`
- 实现后新增测试：`11 passed`
- 工作流骨架 + 总闸测试：`20 passed`
- 全量测试：`76 passed`

覆盖项：

| 用户要求 | 测试状态 |
|---|---|
| 市场极弱时总闸开启 | 已覆盖 |
| 三大指数同步明显下跌时开启 | 已覆盖 |
| 数据过期/不可靠时开启 | 已覆盖 |
| 单个普通风险信号不会误触发 | 已覆盖 |
| 多个风险扩大信号组合后进入 HIGH | 已覆盖 |
| 达到系统性风险组合后锁定新买入 | 已覆盖 |
| 当日锁定后不能自动解除 | 已覆盖 |
| 系统性风险开启后首选和替补不再继续检查 | 已覆盖 |
| 持仓模块不被强制改为全部卖出 | 已覆盖 |
| 下一交易日符合解除条件时可以解除 | 已覆盖 |
| 解锁后只进入待检查状态，不直接变成可买 | 已覆盖 |
| 原有全部测试继续通过 | 已覆盖，`76 passed` |

## 9. 三个历史截面的结果

数据来源：

- 普通震荡/弱市：本地 `data/sqlite/market_120d.sqlite`，覆盖至 `20260710`；
- 20260717 极弱：`reports/fast_context/verified_market_snapshot_20260717.json`。

| 截面 | 市场状态 | 核心指数均值 | 上涨占比 | 总闸风险 | 禁止新买入 | 说明 |
|---|---|---:|---:|---|---|---|
| 20260616 普通震荡 | 震荡 | `+0.8457%` | `49.52%` | `CAUTION` | 否 | 有指数/宽度边际转弱信号，但未触发硬否决，也未达到组合系统性风险 |
| 20260706 普通弱市 | 弱 | `-0.9954%` | `34.00%` | `CAUTION` | 否 | 弱市可保留谨慎试错，不被必然锁死 |
| 20260717 极弱 | 极弱 | `-5.6763%` | `8.73%` | `SYSTEMIC` | 是 | 触发市场极弱、三大指数同步下跌、上涨占比极弱三项硬否决 |

验证结论：

- 普通震荡不会被频繁锁死；
- 普通弱市不会必然禁止新买入，仍可由后续盘中否决继续检查；
- 20260717 明确触发系统性风险总闸。

## 10. 2026-07-16 盲测结果

本轮没有足够完整的 20260716 盲测行情截面：

- 本地 SQLite 只到 `20260710`；
- `reports/tushare/latest_tushare_success_status.json` 显示 20260716 当时有 `daily=5524`、`daily_basic=5524` 的连通与行数证据，但不包含三大指数涨跌、上涨占比完整快照；
- 本轮直连 `scripts/build_verified_market_snapshot.py --today 20260716` 返回 `snapshot_status=BLOCKED`，错误类别 `TIMEOUT`，无法补齐盲测截面。

因此不能给出 20260716 的真实市场风险等级，避免用 20260717 数据倒灌。若按总闸的数据纪律，20260716 当前可复核结果只能是：

- 数据状态：`BLOCKED / TIMEOUT`
- 市场风险：`UNKNOWN`
- 系统性风险信号：无法确认，缺核心截面
- 新买入动作：因数据不可靠触发 `DATA_UNRELIABLE`，应禁止新买入

## 11. 已知能力边界

已具备：

- 一个独立、可测试、可落盘的系统性风险对象；
- 硬否决统一禁止新买入；
- 组合信号透明聚合；
- 上游缺数据时标为 `UNKNOWN`，不当作成立；
- 当日锁定不可自动解除；
- 下一交易日/盘后复核的保守解锁入口；
- 与前夜计划、盘中最终动作、日内执行锁的最小衔接；
- 持仓模块不被总闸强制改成卖出。

仍不具备：

- 不自动发现“原强势板块连续补跌”；
- 不自动聚合“多个板块核心股同时破位”；
- 不自动识别“龙头、中军、后排同步走弱”；
- 不自动识别“防御板块抗跌但整体风险扩大”；
- 不自动调用东方财富或 Tushare；
- 不做盘中自动解锁；
- 不生成买入建议；
- 不接入六爻。

## 12. 是否建议进入第三轮六爻接入

建议进入第三轮，但第三轮只应接入“人工六爻结果写入 + 对现实策略降级”的部分。

原因：

- 工作流状态骨架已经可以承接六爻字段；
- 系统性风险总闸已经能先行挡住新买入，避免六爻结果误升级现实建议；
- 但板块/核心股自动聚合仍是 `UNKNOWN` 为主，第三轮不宜加入自动六爻评分或复杂算法。

建议第三轮边界：

1. 六爻只作为人工输入；
2. 只能降级 `participation_level` 和允许方向；
3. 不得覆盖 `systemic_risk_gate.new_buy_locked=true`；
4. 不得把 `NO_NEW_BUY_SYSTEMIC_RISK` 改成可买；
5. 不改评分、买点、持仓卖出规则。
