# Read-Only Watch Protocol

## Purpose

Monitor confirmed plans with read-only data. Do not execute trades.

## Candidate States

- Reached zone.
- Preliminary support.
- Confirmed support.
- Turning strong.
- Invalidated.
- Data stale or unavailable.

## Holding States

- Support test.
- Recovered.
- Strength confirmed.
- Recovery rejected.
- Support broken.
- Risk escalated.

## Confirmation

Combine the target price, two complete five-minute bars, relative turnover, fund-flow freshness, market state, sector state, and reference stocks. A single fund-flow field must never trigger a conclusion.

## Plan Changes

1. Read the current formal config.
2. Draft updated protection, risk, recovery, and strength levels.
3. Show the proposed plan to the user.
4. Update the formal config only after explicit confirmation.
5. Keep notification delivery separate from execution.
