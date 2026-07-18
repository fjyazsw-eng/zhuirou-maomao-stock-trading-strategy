---
name: stock-strategy-lab
description: Analyze Chinese A-share market conditions, sectors, candidates, and existing holdings with dated evidence, explicit data-quality checks, position-risk conditions, and optional read-only intraday monitoring. Use when users ask for stock analysis, sector comparison, candidate screening, holding consultation, risk plans, daily reports, or watchlist configuration. Never use it to connect brokerage accounts, place orders, automate trading, promise returns, or treat demo data as live data.
---

# Stock Strategy Lab

Use the existing project modules as a research assistant. Keep internal reasoning structured and user output concise.

## Start

1. Locate the package root containing `scoring_system/`, `scripts/`, and `config/`.
2. Read `references/safety-boundaries.md` for every task.
3. Read `references/analysis-protocol.md` for analysis, candidates, sectors, or holdings.
4. Read `references/watch-protocol.md` only for intraday monitoring or watch-plan changes.
5. Run `python scripts/stock_ai.py health-check` before any live-data conclusion.

## Choose The Workflow

- For candidate, sector, or holding analysis, follow:
  `weather -> sector -> leader/core -> stock -> funds/turnover -> fundamentals -> position/risk -> conclusion/conditions`.
- For a watch request, draft the plan first. Change the formal watch config only after the user explicitly confirms it.
- For a new installation without credentials or a database, run `python scripts/stock_ai.py demo`. Label all output `DEMO DATA / 演示数据`.
- Treat 六爻 as an optional comparison note only. Never let it override market data.

## Data Discipline

- State the data source and data date.
- Separate facts, inferences, and action conditions.
- If required data is missing, stale, inconsistent, or from a demo fixture, downgrade to `观察` or `数据不足`.
- Do not invent prices, returns, volumes, fund flow, fundamentals, or sector membership.
- Use Tushare through `scoring_system/tushare_client.py`. Use the Eastmoney client only for read-only intraday supplements.

## Commands

```text
python scripts/stock_ai.py health-check
python scripts/stock_ai.py analyze --input examples/candidate_analysis.json
python scripts/stock_ai.py daily-report
python scripts/stock_ai.py watch-once
python scripts/stock_ai.py watch-start
python scripts/stock_ai.py test
python scripts/stock_ai.py demo
```

## Output

Always include the data date, completeness, conclusion, trigger conditions, invalidation conditions, and risk boundary. Use the detailed schema in `references/analysis-protocol.md`.

Never place an order, connect an account, imply guaranteed returns, or convert an analysis conclusion into automatic execution.
