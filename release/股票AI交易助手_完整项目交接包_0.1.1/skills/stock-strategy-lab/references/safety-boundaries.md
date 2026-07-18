# Safety Boundaries

- Use this package only for research, learning, consultation, monitoring, and review.
- Never connect a real brokerage account.
- Never place or simulate a real order on the user's behalf.
- Never enable automatic trading.
- Never promise returns or describe uncertain conclusions as facts.
- Treat actual holdings as consultation inputs. The user remains responsible for execution.
- Preserve the existing scoring weights, labels, thresholds, and historical validation results unless the user explicitly authorizes a separate model-change task.
- Do not use private validation data for same-day decisions.
- Do not expose tokens, webhooks, API keys, CC Connect sessions, or personal paths.
- Demo fixtures must always display `DEMO DATA / 演示数据` and `不得用于真实交易决策`.
- When live data is missing or stale, say `行情数据不足，暂不判断买点。`
