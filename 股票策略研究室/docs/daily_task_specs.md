# Daily Task Specs

This file defines recurring daily information-collection tasks for Strategy Lab. These tasks are for data collection and evidence organization only. They do not produce trading decisions, trading instructions, or brokerage-account actions.

## Common Rules

- Use real, source-labeled data whenever available.
- Mark each data point as intraday, delayed, historical, or missing.
- Write "数据缺失" when a field cannot be verified.
- Do not infer unavailable data.
- Do not output buy, sell, add, reduce, heavy position, clear position, must rise, or must fall.
- Do not interpret hexagrams in automated data tasks.
- Do not connect to brokerage accounts.
- Do not execute trades.

## Morning Brief

Recommended time: before A-share open.

Purpose:

- Collect overnight overseas market context.
- Collect domestic important news.
- Check current holdings and watchlist announcements.
- List important same-day risk events.
- Produce a short observation-only brief for ChatGPT strategy analysis.

Key sections:

1. Data cutoff time.
2. Overseas markets.
3. Domestic important news.
4. Previous trading day sector funds.
5. Holdings and watchlist announcements.
6. Important risk events.
7. Sector attention list.
8. Observation checklist.
9. Data sources.
10. Missing data.

## 10:30 Intraday Monitor

Recommended time: 10:30 Asia/Shanghai on A-share trading days.

Purpose:

- Collect intraday market facts.
- Compare with the morning brief when available.
- Detect abnormal changes.
- Organize evidence for later strategy analysis.

Scope:

- Holdings or watchlist specified by the user for the current trading day.
- Current default focus: 有研新材 600206.SH, 华天科技 002185.SZ, 晶瑞电材 300655.SZ, 有研硅 688432.SH.

Fixed framework:

1. Weather: major indices, total turnover, advancers, decliners.
2. Neighborhoods: semiconductor, semiconductor materials, lithography/photoresist, advanced packaging, display panel.
3. Class leaders: current factual leaders in the focus sectors.
4. Shops: user holdings, latest price, percent change, turnover, volume, relative strength, abnormal behavior.
5. Abnormal changes.
6. Afternoon observation checklist.
7. Data sources.
8. Missing data.

## Closing Review

Recommended time: after A-share close and after main announcements begin to appear.

Purpose:

- Summarize market weather and sector performance.
- Review holdings and focus stocks.
- Collect risk warnings, abnormal-move announcements, inquiry letters, regulatory concerns, and major-event disclosures.
- Explain the meaning of risk notices without converting them into trading decisions.

Key sections:

1. Data cutoff time.
2. Market weather.
3. Key sectors.
4. Core stock changes.
5. Holdings performance.
6. Risk-notice announcement summary.
7. Important risk notices explained one by one.
8. Possible impact on focus sectors.
9. Possible impact on holdings.
10. Next-day observation items.
11. Data sources.
12. Missing data.

## Data Retention

Recommended output locations when file writing is requested:

- Morning brief: `reports/daily/YYYY-MM-DD_morning_brief.md`
- 10:30 monitor: `reports/daily/YYYY-MM-DD_1030_monitor.md`
- Closing review: `reports/review/YYYY-MM-DD_closing_review.md`
- Raw data snapshots: `data/raw/YYYY-MM-DD/`
- Processed summaries: `data/processed/YYYY-MM-DD/`
