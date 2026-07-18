# Analysis Protocol

## Input

Candidate analysis:

```json
{
  "task": "candidate_analysis",
  "trade_date": "latest",
  "capital": 5000,
  "holding_period": "2-4周",
  "max_candidates": 3,
  "constraints": {
    "max_price": 50,
    "cannot_watch_intraday": true
  }
}
```

Holding analysis:

```json
{
  "task": "holding_analysis",
  "positions": [
    {"ts_code": "000001.SZ", "cost": 10.5, "shares": 100}
  ],
  "holding_period": "1-2周"
}
```

## Workflow

1. Verify data source, date, freshness, and completeness.
2. Assess market weather and risk appetite.
3. Assess the relevant sector cycle and breadth.
4. Identify the leader/core and classify the target stock's role.
5. Check price structure, volume, turnover, and available fund flow.
6. Use fundamentals for risk screening, not as a substitute for a valid entry condition.
7. Apply position and risk limits.
8. Produce a clear conclusion with triggers and invalidation.

## Output

Include:

- Data date.
- Data completeness and stale status.
- Market weather.
- Sector state.
- Stock role.
- Funds and turnover.
- Fundamentals summary.
- Main risks.
- Clear conclusion.
- Execution conditions.
- Invalidation conditions.
- Position ceiling.
- Stop-loss or profit-protection condition.
- Facts separated from inferences.

When data is incomplete, output `观察` or `数据不足`; never force a buy conclusion.

## Example Output

```text
数据日期：2026-01-05
数据完整性：日线完整；盘中数据缺失
事实：价格仍在20日均线上方，所属板块近5日强于市场。
推断：趋势尚未破坏，但当前无法确认盘中承接。
结论：观察，不追高。
触发条件：回踩关键位后量价恢复，并且板块核心同步走强。
失效条件：跌破风险线且无法收回。
仓位上限：数据完整前为0%。
```
