"""Tushare daily endpoint focused test.

Safety rules:
- Never print the full Tushare token.
- Only test the daily endpoint for TEST_DATE.
- Prefer the local CSV cache when it already exists and has complete fields.
- Do not call trade_cal or stock_basic here, to avoid unnecessary API usage.
- This script checks data access only; it does not generate trading advice.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

TEST_DATE = "20260630"
REQUIRED_FIELDS = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]
FIELDS = ",".join(REQUIRED_FIELDS)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "raw" / f"daily_{TEST_DATE}.csv"

RATE_LIMIT_HINTS = ("频率超限", "每小时", "每分钟", "每秒", "rate limit")
PERMISSION_HINTS = ("权限", "积分", "permission", "not allowed", "没有访问")


def classify_exception(exc: Exception) -> str:
    message = str(exc)
    lower = message.lower()
    if any(hint.lower() in lower for hint in RATE_LIMIT_HINTS):
        return "程序异常"
    if any(hint.lower() in lower for hint in PERMISSION_HINTS):
        return "无权限"
    return "程序异常"


def print_result(source: str, df) -> int:
    columns = list(df.columns)
    missing = [field for field in REQUIRED_FIELDS if field not in columns]
    print(f"数据来源: {source}")
    print(f"测试日期: {TEST_DATE}")
    print(f"返回字段: {','.join(columns)}")
    print(f"行数: {len(df)}")
    print("前5行:")
    print(df.head(5).to_string(index=False))
    if missing:
        print(f"字段完整性: 缺少 {','.join(missing)}")
        print("说明: 以上为Tushare或本地CSV原始返回字段，未伪造缺失字段。")
        return 2
    print("字段完整性: 完整")
    return 0


def main() -> int:
    print("Tushare daily接口检查")
    print(f"Python版本: {sys.version.split()[0]}")

    try:
        import pandas as pd
        print(f"pandas版本: {pd.__version__}")
    except Exception as exc:
        print(f"pandas检查: 程序异常: {exc}")
        return 1

    if OUTPUT_PATH.exists():
        try:
            cached = pd.read_csv(OUTPUT_PATH)
        except Exception as exc:
            print(f"本地文件读取异常，将尝试调用API: {exc}")
        else:
            cached_missing = [field for field in REQUIRED_FIELDS if field not in cached.columns]
            if len(cached) > 0 and not cached_missing:
                print(f"本地文件已存在且数据完整: {OUTPUT_PATH}")
                return print_result("本地CSV缓存", cached)
            print(f"本地文件存在但不完整，将尝试调用API: {OUTPUT_PATH}")
            if cached_missing:
                print(f"本地文件缺少字段: {','.join(cached_missing)}")

    try:
        import tushare as ts
        print(f"tushare版本: {getattr(ts, '__version__', 'unknown')}")
    except Exception as exc:
        print(f"tushare检查: 程序异常: {exc}")
        return 1

    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        print("TUSHARE_TOKEN: 不存在")
        return 1
    print(f"TUSHARE_TOKEN: 存在，长度={len(token)}，不打印完整Token")

    ts.set_token(token)
    pro = ts.pro_api()
    print(f"daily fields参数: {FIELDS}")

    try:
        df = pro.daily(trade_date=TEST_DATE, fields=FIELDS)
    except Exception as exc:
        print(f"daily: {classify_exception(exc)}，{exc}")
        return 1

    if len(df) == 0:
        print("daily: 无数据")
        print("返回字段: " + ",".join(df.columns))
        return 2

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"已保存: {OUTPUT_PATH}")
    return print_result("Tushare daily API", df)


if __name__ == "__main__":
    raise SystemExit(main())
