"""Tushare stage-1 interface access check.

Interfaces tested, at most once each when cache is incomplete:
1. trade_cal
2. stock_basic
3. daily_basic
4. index_basic
5. index_daily

No full token printing. No brokerage access. No trading suggestions.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pandas as pd
import tushare as ts

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
BASIC_DIR = PROJECT_ROOT / "data" / "basic"
TEST_DATE = "20260630"
SLEEP_SECONDS = 1.5


@dataclass
class InterfaceTask:
    name: str
    path: Path
    fields: list[str]
    call: Callable[[object], pd.DataFrame]
    data_date: str


@dataclass
class InterfaceResult:
    name: str
    status: str
    rows: int
    fields: list[str]
    data_date: str
    cache_path: Path
    source: str
    message: str = ""


PERMISSION_HINTS = ("权限", "积分", "permission", "not allowed", "没有访问", "抱歉")
NETWORK_HINTS = ("timeout", "timed out", "connection", "network", "远程", "连接", "网络")


def classify_error(exc: Exception) -> str:
    message = str(exc).lower()
    if any(hint.lower() in message for hint in NETWORK_HINTS):
        return "网络异常"
    if any(hint.lower() in message for hint in PERMISSION_HINTS):
        return "权限不足"
    return "网络异常"


def cache_complete(path: Path, fields: list[str]) -> tuple[bool, pd.DataFrame | None]:
    if not path.exists():
        return False, None
    try:
        df = pd.read_csv(path)
    except Exception:
        return False, None
    missing = [field for field in fields if field not in df.columns]
    if missing or len(df) == 0:
        return False, df
    return True, df


def safe_result_from_df(task: InterfaceTask, status: str, df: pd.DataFrame, source: str) -> InterfaceResult:
    return InterfaceResult(
        name=task.name,
        status=status,
        rows=len(df),
        fields=[str(col) for col in df.columns],
        data_date=task.data_date,
        cache_path=task.path,
        source=source,
    )


def run_task(task: InterfaceTask, pro: object, should_sleep: bool) -> InterfaceResult:
    complete, cached = cache_complete(task.path, task.fields)
    if complete and cached is not None:
        return safe_result_from_df(task, "成功", cached, "本地缓存")

    if should_sleep:
        time.sleep(SLEEP_SECONDS)

    try:
        df = task.call(pro)
    except Exception as exc:
        return InterfaceResult(task.name, classify_error(exc), 0, [], task.data_date, task.path, "API", str(exc))

    if len(df) == 0:
        return InterfaceResult(task.name, "无数据", 0, [str(col) for col in df.columns], task.data_date, task.path, "API")

    task.path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(task.path, index=False, encoding="utf-8-sig")
    return safe_result_from_df(task, "成功", df, "API")


def build_tasks() -> list[InterfaceTask]:
    return [
        InterfaceTask(
            name="trade_cal",
            path=BASIC_DIR / f"trade_cal_{TEST_DATE}.csv",
            fields=["exchange", "cal_date", "is_open", "pretrade_date"],
            data_date=TEST_DATE,
            call=lambda pro: pro.trade_cal(exchange="", start_date=TEST_DATE, end_date=TEST_DATE, fields="exchange,cal_date,is_open,pretrade_date"),
        ),
        InterfaceTask(
            name="stock_basic",
            path=BASIC_DIR / "stock_basic.csv",
            fields=["ts_code", "symbol", "name", "area", "industry", "list_date"],
            data_date="latest_available",
            call=lambda pro: pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name,area,industry,list_date"),
        ),
        InterfaceTask(
            name="daily_basic",
            path=RAW_DIR / f"daily_basic_{TEST_DATE}.csv",
            fields=["ts_code", "trade_date", "close", "turnover_rate", "volume_ratio", "pe", "pb", "total_mv", "circ_mv"],
            data_date=TEST_DATE,
            call=lambda pro: pro.daily_basic(trade_date=TEST_DATE, fields="ts_code,trade_date,close,turnover_rate,volume_ratio,pe,pb,total_mv,circ_mv"),
        ),
        InterfaceTask(
            name="index_basic",
            path=BASIC_DIR / "index_basic_SSE.csv",
            fields=["ts_code", "name", "market", "publisher", "category", "base_date", "list_date"],
            data_date="latest_available_SSE",
            call=lambda pro: pro.index_basic(market="SSE", fields="ts_code,name,market,publisher,category,base_date,list_date"),
        ),
        InterfaceTask(
            name="index_daily",
            path=RAW_DIR / f"index_daily_000001_SH_{TEST_DATE}.csv",
            fields=["ts_code", "trade_date", "close", "open", "high", "low", "pre_close", "change", "pct_chg", "vol", "amount"],
            data_date=TEST_DATE,
            call=lambda pro: pro.index_daily(ts_code="000001.SH", trade_date=TEST_DATE, fields="ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount"),
        ),
    ]


def main() -> int:
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        print("TUSHARE_TOKEN: 不存在")
        return 1
    print(f"TUSHARE_TOKEN: 存在，长度={len(token)}，不打印完整Token")
    pro = ts.pro_api(token)

    results: list[InterfaceResult] = []
    api_attempted_before = False
    for task in build_tasks():
        complete, _cached = cache_complete(task.path, task.fields)
        result = run_task(task, pro, should_sleep=api_attempted_before and not complete)
        if not complete and result.source == "API":
            api_attempted_before = True
        results.append(result)

    print("接口,状态,行数,数据日期,缓存路径,字段")
    for result in results:
        print(
            f"{result.name},{result.status},{result.rows},{result.data_date},{result.cache_path},{'|'.join(result.fields)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
