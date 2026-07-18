# 2025 封闭测试题模板

每道测试题都必须使用同一结构，便于复查、评分和防未来函数。

```yaml
test_id:
test_name:
test_type:
as_of_date:
stage_a_window:
  start:
  end:
stage_b_window:
  start:
  end:
user_state:
  empty_or_holding:
  cash:
  total_assets:
  holdings:
    - ts_code:
      name:
      shares:
      cost:
      sector:
      role:
  can_watch_market:
question:
allowed_data:
  - trade_date <= as_of_date
  - market_2025.sqlite 阶段A快照
forbidden_data:
  - as_of_date 之后行情
  - 阶段B收益
  - 未来公告、未来新闻、未来复盘
  - 当前概念股名单倒推历史概念池
expected_outputs:
  market_weather:
  sector_cycle:
  sector_aux_labels:
  stock_role:
  execution_label:
  position_size:
  holding_action:
  account_risk:
  no_watch_action:
  buy_allowed:
  max_position:
  stop_loss:
  profit_protection:
stage_a_snapshot:
  path:
  sha256:
  generated_at:
stage_b_validation:
  price_result:
  max_drawdown:
  opportunity_cost:
  whether_advice_helped:
  validation_type:
score:
  data_discipline_score:
  judgment_score:
  execution_position_score:
  holding_profit_score:
  account_risk_score:
  review_quality_score:
  total_score:
conclusion:
  passed:
  main_errors:
  next_fix:
```

## 字段要求

- `as_of_date` 是阶段A截止日。
- `stage_a_window.end` 不得晚于 `as_of_date`。
- `stage_b_window` 只能在阶段A快照保存后读取。
- `holdings` 必须写明成本和数量，不能只写“持有”。
- `can_watch_market` 会影响仓位和执行标签。
- `allowed_data` 和 `forbidden_data` 必须逐题写清。
- `stage_a_snapshot.sha256` 必须可复算。

## 无效测试标记

如果数据不足，必须标记：

```yaml
conclusion:
  passed: false
  main_errors:
    - 数据不足，无法构造有效测试
```

不能为了让题目成立而临时编板块成分、编政策事件或用未来热门股倒推。
