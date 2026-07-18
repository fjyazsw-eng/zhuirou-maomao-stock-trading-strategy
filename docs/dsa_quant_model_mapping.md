# DSA Quant Model Mapping

## Goal

Use DailyStockAnalysis as the reporting and orchestration layer, while keeping Tushare as the primary verified data source.

## Observed DSA Traits

- Multi-source data layer
- Daily report and watchlist style workflow
- AI-generated decision summaries
- Web UI and scheduled runs
- Tushare supported directly

## Screenshot-Derived UI Pattern

- Top: holding-period validation summary
- Middle: candidate ranking table
- Table columns: stock, score, buy date, buy price source, entry price, current price, 1-5 day returns
- Core idea: score first, validate later, then show candidate list

## Proposed Decision Hierarchy

### 1. Weather
Market regime.

Inputs:
- index trend
- liquidity
- breadth
- volatility
- risk appetite

Output:
- market state score
- risk gate

### 2. District
Sector or theme strength.

Inputs:
- sector return
- sector turnover
- sector money flow
- breadth within sector

Output:
- hot district ranking
- district continuation probability

### 3. Captain
Leader confirmation.

Inputs:
- relative strength
- breakout behavior
- volume confirmation
- money flow concentration

Output:
- whether the district has a real leader
- leader confidence score

### 4. Store
Single stock evaluation.

Inputs:
- price action
- volume
- money flow
- fundamentals
- event risk

Output:
- stock score
- entry condition status
- invalidation conditions

## Recommended System Shape

### Layer A: Data

- Tushare for verified A-share data
- local SQLite cache for fast reuse
- DSA fetchers for multi-source fallback

### Layer B: Scoring

- weather score
- district score
- captain score
- store score

### Layer C: Validation

- 1/2/3/4/5 day forward checks
- win rate
- average return
- drawdown

### Layer D: Report

- one daily decision report
- fact / inference separation
- no final trade command

## Why This Works

- Keeps the logic close to real market structure
- Avoids one-shot black-box prediction
- Lets DSA act as a shell around a stable model
- Allows local debugging and gradual replacement of pieces

## Next Practical Step

Build a small proof-of-concept that:

1. Reads Tushare data
2. Produces weather / district / captain / store scores
3. Generates one candidate table
4. Validates forward returns
