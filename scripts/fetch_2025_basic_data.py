from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scoring_system.network_env import clear_bad_tushare_proxy
except Exception:  # pragma: no cover
    clear_bad_tushare_proxy = None


DEFAULT_BASE_DIR = Path("D:/股票AI交易助手数据")
DEFAULT_DB_PATH = DEFAULT_BASE_DIR / "sqlite" / "market_2025.sqlite"
DEFAULT_CACHE_DIR = DEFAULT_BASE_DIR / "cache" / "tushare_2025"
DEFAULT_TEMP_DIR = DEFAULT_BASE_DIR / "temp" / "fetch_2025"
DEFAULT_LOG_DIR = DEFAULT_BASE_DIR / "logs" / "fetch_2025"
REPORT_DIR = ROOT / "reports" / "data"
REQUIRED_TABLES = ["trade_cal", "stock_basic", "daily", "daily_basic", "adj_factor", "index_daily", "limit_list", "suspend"]
INDEX_CODES = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "000300.SH", "000905.SH", "000852.SH"]


@dataclass
class FetchResult:
    table_name: str
    status: str
    row_count: int = 0
    start_date: str = ""
    end_date: str = ""
    message: str = ""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_path(value: str | Path) -> Path:
    return Path(str(value).replace("\\", "/"))


def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def token_value() -> str:
    load_dotenv()
    return os.environ.get("TUSHARE_TOKEN", "") or os.environ.get("TUSHARE_TOKEN_PRO", "")


def make_dirs(db_path: Path, cache_dir: Path, temp_dir: Path, log_dir: Path) -> None:
    for path in [db_path.parent, cache_dir, temp_dir, log_dir, REPORT_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def assert_not_c_drive(path: Path, label: str) -> None:
    drive = path.resolve().drive.upper()
    if drive.startswith("C:"):
        raise RuntimeError(f"{label} 不允许写入 C 盘: {path}")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def create_meta_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS data_manifest (
            dataset_name TEXT PRIMARY KEY,
            db_path TEXT,
            start_date TEXT,
            end_date TEXT,
            created_at TEXT,
            updated_at TEXT,
            source TEXT,
            notes TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS table_coverage (
            table_name TEXT PRIMARY KEY,
            start_date TEXT,
            end_date TEXT,
            row_count INTEGER,
            status TEXT,
            last_fetch_at TEXT,
            message TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fetch_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT,
            start_date TEXT,
            end_date TEXT,
            status TEXT,
            row_count INTEGER,
            error_message TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def cache_path(cache_dir: Path, table: str, key: str) -> Path:
    folder = cache_dir / table
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{table}_{key}.csv"


def read_cache(path: Path) -> pd.DataFrame:
    if path.exists() and path.stat().st_size > 0:
        return pd.read_csv(path, dtype=str)
    return pd.DataFrame()


def write_cache(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def fetch_with_cache(path: Path, fetcher: Callable[[], pd.DataFrame], resume: bool) -> tuple[pd.DataFrame, str]:
    if resume and path.exists():
        return read_cache(path), "cache"
    df = fetcher()
    if df is None:
        df = pd.DataFrame()
    write_cache(df, path)
    return df, "fetched"


def delete_existing(conn: sqlite3.Connection, table: str, date_col: str, start: str, end: str, extra_where: str = "", params: tuple[Any, ...] = ()) -> None:
    if not table_exists(conn, table):
        return
    sql = f"DELETE FROM {table} WHERE {date_col} >= ? AND {date_col} <= ?"
    values: tuple[Any, ...] = (start, end)
    if extra_where:
        sql += f" AND {extra_where}"
        values += params
    conn.execute(sql, values)


def append_df(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    clean = df.copy()
    clean.columns = [str(c).strip() for c in clean.columns]
    clean.to_sql(table, conn, if_exists="append", index=False)
    return int(len(clean))


def replace_df(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> int:
    clean = df.copy()
    clean.columns = [str(c).strip() for c in clean.columns]
    clean.to_sql(table, conn, if_exists="replace", index=False)
    return int(len(clean))


def log_fetch(conn: sqlite3.Connection, result: FetchResult) -> None:
    conn.execute(
        "INSERT INTO fetch_log(table_name,start_date,end_date,status,row_count,error_message,created_at) VALUES(?,?,?,?,?,?,?)",
        (result.table_name, result.start_date, result.end_date, result.status, result.row_count, result.message, now()),
    )
    conn.execute(
        """
        INSERT INTO table_coverage(table_name,start_date,end_date,row_count,status,last_fetch_at,message)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(table_name) DO UPDATE SET
          start_date=excluded.start_date,
          end_date=excluded.end_date,
          row_count=excluded.row_count,
          status=excluded.status,
          last_fetch_at=excluded.last_fetch_at,
          message=excluded.message
        """,
        (result.table_name, result.start_date, result.end_date, result.row_count, result.status, now(), result.message),
    )
    conn.commit()


def date_col_for(table: str) -> str:
    return "cal_date" if table == "trade_cal" else "trade_date"


def safe_fetch(table: str, start: str, end: str, fn: Callable[[], int], conn: sqlite3.Connection) -> FetchResult:
    try:
        rows = fn()
        result = FetchResult(table, "OK", rows, start, end, "")
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        existing = table_summary(conn, table)
        existing_rows = int(existing.get("rows") or 0)
        if existing_rows > 0:
            lower = msg.lower()
            status = "PARTIAL_WITH_RATE_LIMIT" if any(x in lower for x in ["limit", "??", "rate"]) else "PARTIAL_FETCHED"
            message = (
                f"{msg[:300]}?????? {existing_rows} ??"
                f"?? {existing.get('start') or '-'} ? {existing.get('end') or '-'}?"
                f"?? {existing.get('end') or '-'} ??? {end} ???????"
            )
            result = FetchResult(table, status, existing_rows, start, end, message)
        else:
            status = "MISSING_OR_NO_PERMISSION" if any(x in msg.lower() for x in ["permission", "??", "??", "??", "limit", "not found"]) else "FAILED"
            result = FetchResult(table, status, 0, start, end, msg[:500])
    log_fetch(conn, result)
    return result


def pro_api() -> Any:
    if clear_bad_tushare_proxy:
        clear_bad_tushare_proxy()
    token = token_value()
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 不可见")
    import tushare as ts

    return ts.pro_api(token)


def trade_dates_from_db(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    if not table_exists(conn, "trade_cal"):
        return []
    rows = conn.execute(
        "SELECT cal_date FROM trade_cal WHERE cal_date>=? AND cal_date<=? AND is_open='1' ORDER BY cal_date",
        (start, end),
    ).fetchall()
    return [str(x[0]) for x in rows]


def fetch_trade_cal(pro: Any, conn: sqlite3.Connection, cache_dir: Path, start: str, end: str, resume: bool) -> int:
    path = cache_path(cache_dir, "trade_cal", f"{start}_{end}")
    df, _ = fetch_with_cache(
        path,
        lambda: pro.trade_cal(exchange="", start_date=start, end_date=end, fields="exchange,cal_date,is_open,pretrade_date"),
        resume,
    )
    delete_existing(conn, "trade_cal", "cal_date", start, end)
    return append_df(conn, "trade_cal", df)


def fetch_stock_basic(pro: Any, conn: sqlite3.Connection, cache_dir: Path, resume: bool) -> int:
    path = cache_path(cache_dir, "stock_basic", "all")
    df, _ = fetch_with_cache(
        path,
        lambda: pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,symbol,name,area,industry,market,list_date,exchange,curr_type,list_status,delist_date,is_hs",
        ),
        resume,
    )
    return replace_df(conn, "stock_basic", df)


def fetch_by_trade_date(pro: Any, conn: sqlite3.Connection, cache_dir: Path, table: str, dates: list[str], resume: bool) -> int:
    total = 0
    for i, date in enumerate(dates, 1):
        path = cache_path(cache_dir, table, date)
        if table == "daily":
            fetcher = lambda d=date: pro.daily(trade_date=d)
        elif table == "daily_basic":
            fetcher = lambda d=date: pro.daily_basic(trade_date=d)
        elif table == "adj_factor":
            fetcher = lambda d=date: pro.adj_factor(trade_date=d)
        elif table == "limit_list":
            fetcher = lambda d=date: pro.limit_list(trade_date=d)
        elif table == "suspend":
            fetcher = lambda d=date: pro.suspend_d(trade_date=d)
        else:
            raise ValueError(table)
        df, _ = fetch_with_cache(path, fetcher, resume)
        delete_existing(conn, table, "trade_date", date, date)
        total += append_df(conn, table, df)
        if i % 20 == 0:
            conn.commit()
            time.sleep(0.2)
    conn.commit()
    return total


def fetch_index_daily(pro: Any, conn: sqlite3.Connection, cache_dir: Path, start: str, end: str, resume: bool) -> int:
    total = 0
    for code in INDEX_CODES:
        key = f"{code.replace('.', '_')}_{start}_{end}"
        path = cache_path(cache_dir, "index_daily", key)
        df, _ = fetch_with_cache(
            path,
            lambda c=code: pro.index_daily(ts_code=c, start_date=start, end_date=end),
            resume,
        )
        delete_existing(conn, "index_daily", "trade_date", start, end, "ts_code=?", (code,))
        total += append_df(conn, "index_daily", df)
        time.sleep(0.2)
    conn.commit()
    return total


def update_manifest(conn: sqlite3.Connection, db_path: Path, start: str, end: str) -> None:
    created = now()
    row = conn.execute("SELECT created_at FROM data_manifest WHERE dataset_name='market_2025'").fetchone()
    if row and row[0]:
        created = str(row[0])
    conn.execute(
        """
        INSERT INTO data_manifest(dataset_name,db_path,start_date,end_date,created_at,updated_at,source,notes)
        VALUES('market_2025',?,?,?,?,?,'tushare','2025 basic data MVP')
        ON CONFLICT(dataset_name) DO UPDATE SET
          db_path=excluded.db_path,
          start_date=excluded.start_date,
          end_date=excluded.end_date,
          updated_at=excluded.updated_at,
          source=excluded.source,
          notes=excluded.notes
        """,
        (str(db_path), start, end, created, now()),
    )
    conn.commit()


def table_summary(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    if not table_exists(conn, table):
        return {"table": table, "exists": False, "rows": 0, "start": "", "end": ""}
    rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    col = date_col_for(table)
    try:
        start, end = conn.execute(f"SELECT MIN({col}), MAX({col}) FROM {table}").fetchone()
    except Exception:
        start, end = "", ""
    return {"table": table, "exists": True, "rows": int(rows), "start": start or "", "end": end or ""}


def write_report(db_path: Path, cache_dir: Path, temp_dir: Path, log_dir: Path, start: str, end: str, results: list[FetchResult], summaries: list[dict[str, Any]]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORT_DIR / "2025_data_fetch_report.md"
    lines = [
        "# 2025 基础数据搬运报告",
        "",
        f"- 生成时间：{now()}",
        f"- 数据库路径：`{db_path}`",
        f"- 数据库是否位于D盘：{'是' if db_path.resolve().drive.upper().startswith('D:') else '否'}",
        f"- 缓存目录：`{cache_dir}`",
        f"- 临时目录：`{temp_dir}`",
        f"- 日志目录：`{log_dir}`",
        f"- 拉取范围：{start} 至 {end}",
        f"- 是否支持断点续跑：是，缓存存在时可使用 `--resume`",
        "",
        "## 拉取结果",
        "",
        "| 表 | 状态 | 行数 | 说明 |",
        "| -- | -- | --: | -- |",
    ]
    for item in results:
        lines.append(f"| {item.table_name} | {item.status} | {item.row_count} | {item.message or '-'} |")
    lines += ["", "## 表覆盖概览", "", "| 表 | 是否存在 | 行数 | 起始日期 | 结束日期 |", "| -- | -- | --: | -- | -- |"]
    for item in summaries:
        lines.append(f"| {item['table']} | {'是' if item['exists'] else '否'} | {item['rows']} | {item['start']} | {item['end']} |")
    lines += [
        "",
        "## 边界",
        "",
        "- 本轮只搬运基础行情数据，不运行2025测试题。",
        "- 未修改模型规则，未修改评分权重，未自动交易，未接真实账户。",
        "- 历史概念成分池、新闻公告、盘口承接、分钟级数据后置。",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch 2025 basic Tushare data into a D-drive SQLite database.")
    parser.add_argument("--start", default="20250101")
    parser.add_argument("--end", default="20251231")
    parser.add_argument("--table", choices=["all", *REQUIRED_TABLES], default="all")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--temp-dir", default=str(DEFAULT_TEMP_DIR))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    start = args.start.replace("-", "")
    end = args.end.replace("-", "")
    db_path = normalize_path(args.db_path)
    cache_dir = normalize_path(args.cache_dir)
    temp_dir = normalize_path(args.temp_dir)
    log_dir = normalize_path(args.log_dir)

    assert_not_c_drive(db_path, "数据库")
    assert_not_c_drive(cache_dir, "缓存")
    assert_not_c_drive(temp_dir, "临时目录")
    assert_not_c_drive(log_dir, "日志")
    make_dirs(db_path, cache_dir, temp_dir, log_dir)

    pro = pro_api()
    conn = connect(db_path)
    create_meta_tables(conn)
    update_manifest(conn, db_path, start, end)

    selected = REQUIRED_TABLES if args.table == "all" else [args.table]
    results: list[FetchResult] = []

    if "trade_cal" in selected or args.table == "all":
        results.append(safe_fetch("trade_cal", start, end, lambda: fetch_trade_cal(pro, conn, cache_dir, start, end, args.resume), conn))
    dates = trade_dates_from_db(conn, start, end)
    if not dates and any(t in selected for t in ["daily", "daily_basic", "adj_factor", "limit_list", "suspend"]):
        raise RuntimeError("trade_cal 缺失或无开放交易日，无法按交易日搬运")

    if "stock_basic" in selected:
        results.append(safe_fetch("stock_basic", start, end, lambda: fetch_stock_basic(pro, conn, cache_dir, args.resume), conn))
    if "daily" in selected:
        results.append(safe_fetch("daily", start, end, lambda: fetch_by_trade_date(pro, conn, cache_dir, "daily", dates, args.resume), conn))
    if "daily_basic" in selected:
        results.append(safe_fetch("daily_basic", start, end, lambda: fetch_by_trade_date(pro, conn, cache_dir, "daily_basic", dates, args.resume), conn))
    if "adj_factor" in selected:
        results.append(safe_fetch("adj_factor", start, end, lambda: fetch_by_trade_date(pro, conn, cache_dir, "adj_factor", dates, args.resume), conn))
    if "index_daily" in selected:
        results.append(safe_fetch("index_daily", start, end, lambda: fetch_index_daily(pro, conn, cache_dir, start, end, args.resume), conn))
    if "limit_list" in selected:
        results.append(safe_fetch("limit_list", start, end, lambda: fetch_by_trade_date(pro, conn, cache_dir, "limit_list", dates, args.resume), conn))
    if "suspend" in selected:
        results.append(safe_fetch("suspend", start, end, lambda: fetch_by_trade_date(pro, conn, cache_dir, "suspend", dates, args.resume), conn))

    summaries = [table_summary(conn, table) for table in REQUIRED_TABLES]
    report = write_report(db_path, cache_dir, temp_dir, log_dir, start, end, results, summaries)
    conn.close()

    output = {
        "status": "OK",
        "db_path": str(db_path),
        "cache_dir": str(cache_dir),
        "report": str(report),
        "results": [item.__dict__ for item in results],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
