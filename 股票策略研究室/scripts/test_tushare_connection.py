"""Minimal Tushare connection test.

This script verifies that the local environment can read HITHINK_FINANCE_API_KEY and call
one low-risk Tushare endpoint. It does not fetch market quotes, analyze stocks,
connect to brokerage accounts, or generate trading suggestions.
"""

from __future__ import annotations
from scoring_system.tushare_client import credential_marker

import os
import sys


RATE_LIMIT_HINTS = ("频率超限", "每小时", "每分钟", "每秒")


def main() -> int:
    token = credential_marker()
    if not token:
        print("FAIL: HITHINK_FINANCE_API_KEY was not found in the current environment.")
        print("Hint: reopen the terminal or Codex after running setx.")
        return 1

    try:
        from scoring_system import tushare_client as ts
    except ImportError:
        print("FAIL: tushare is not installed in this Python environment.")
        print("Hint: run: python -m pip install tushare")
        return 1

    print(f"Python: {sys.version.split()[0]}")
    print(f"Tushare: {getattr(ts, '__version__', 'unknown')}")
    print(f"HITHINK_FINANCE_API_KEY: loaded, length={len(token)}")

    ts.set_token(token)
    pro = ts.pro_api()

    try:
        df = pro.trade_cal(exchange="", start_date="20260601", end_date="20260630")
    except Exception as exc:  # Tushare raises plain Exception for API errors.
        message = str(exc)
        print(f"Tushare API returned: {message}")
        if any(hint in message for hint in RATE_LIMIT_HINTS):
            print("PARTIAL PASS: token and SDK are available, but the test endpoint is rate-limited.")
            return 2
        if "权限" in message or "积分" in message:
            print("PARTIAL PASS: token and SDK are available, but this endpoint needs more Tushare permission/points.")
            return 2
        print("FAIL: Tushare API call failed for a reason other than rate limits.")
        return 1

    print(f"trade_cal rows: {len(df)}")
    print("trade_cal sample:")
    print(df.head(5).to_string(index=False))
    print("PASS: Tushare connection test succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
