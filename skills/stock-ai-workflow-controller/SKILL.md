---
name: stock-ai-workflow-controller
description: Use as the top-level controller for the stock AI assistant weekly workflow, portable startup, status checks, next-step routing, systemic-risk gating, manual hexagram downgrade calibration, intraday veto, holding review, and weekly review.
---
## 股票数据源强制入口

先读取仓库根目录 `DATA_SOURCES.md`。所有 A 股取数强制 hithink-finance -> mootdx（仅分钟线），无 Tushare 或其他自动回退。旧报告/备份不是现行取数规则。


# Stock AI Workflow Controller

This is the top-level controller Skill for 股票AI交易助手.

It does not contain the full strategy rules. It routes work to existing modules and enforces the workflow boundary.

## Read First

Before acting, read:

1. `PROJECT_CONTEXT.md`
2. `WORKFLOW_QUICKSTART.md`
3. `reports/workflow/current_workflow_state.json`

For trading-rule details, use the existing three-module rules Skill and the project modules below.

## Core Modules

- Workflow state: `scoring_system/workflow_state.py`
- Workflow orchestrator: `scoring_system/workflow_orchestrator.py`
- Systemic risk gate: `scoring_system/systemic_risk_gate.py`
- Manual hexagram calibration: `scoring_system/hexagram_calibration.py`
- Intraday watch/veto base: `scoring_system/realtime_watch_monitor.py`
- Verified market snapshot: `scoring_system/verified_market_snapshot.py`

## Fixed Priority

Always apply this order:

1. Data reliability
2. Systemic risk gate
3. Reality market analysis
4. Manual hexagram downgrade-only calibration
5. Night-before candidates
6. Intraday veto
7. Holding management
8. Review

Lower layers must never override higher-layer prohibitions.

## Workflow Routing

Use:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts\run_project.py status
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts\run_project.py next
```

Do not skip required stages:

- `WEEKEND_REALITY_PENDING` -> weekend reality analysis
- `WEEKEND_HEXAGRAM_PENDING` -> manual hexagram input
- `WEEKLY_STRATEGY_READY` -> weekly strategy generation
- `NIGHT_PLAN_READY` -> night plan
- `INTRADAY_CHECK_PENDING` -> intraday check
- `INTRADAY_CHECK_COMPLETED` -> closing review
- `CLOSING_REVIEW_COMPLETED` -> next night plan or weekly review

## Hard Boundaries

- Do not auto-cast hexagrams.
- Do not auto-interpret hexagrams.
- Hexagram results can downgrade reality conclusions only; they must never upgrade.
- If the systemic risk gate is locked, hexagram results cannot unlock it.
- Before the systemic risk gate is formally released, reversal observation cannot execute a buy.
- Intraday checks may inspect only the night-plan primary and backup candidates.
- Intraday checks must not generate a third stock.
- Do not auto-trade.
- Do not place real orders.
- Do not connect real brokerage accounts.
- Do not use future data.
- Do not change thresholds to make tests or historical scenarios pass.
- Do not modify scoring weights, A/B buy points, the 100-share rule, holding sell rules, systemic-risk rules, or hexagram mappings unless the user explicitly opens a new rule-change task.

## Stop Conditions

Stop and report instead of continuing when:

- Setup status is `NOT_READY`.
- Workflow state is invalid.
- Data is missing, stale, or unreliable for the requested business step.
- The requested command would skip a required stage.
- The user asks for a buy decision while systemic risk is locked.
- The user asks for intraday re-selection beyond primary and backup.

## Output Format

For status-style answers, include:

- Current stage
- Current trade date
- Completed steps
- Missing steps
- Systemic risk level
- New-buy lock status
- Hexagram validity
- Reversal status
- Next command

For business steps, include:

- Step run
- Input source
- Result
- Whether state changed
- Next command
- Any blocking reason

Keep stock-facing language plain Chinese.
