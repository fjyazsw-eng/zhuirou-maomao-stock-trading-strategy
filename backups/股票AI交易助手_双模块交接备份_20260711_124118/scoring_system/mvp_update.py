from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from scoring_system.data_cache import create_standard_indexes, safe_merge_table, table_stats
from scoring_system.network_env import clear_bad_tushare_proxy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROOT = PROJECT_ROOT / "股票策略研究室"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw" / "tushare"
SQLITE_DIR = DATA_DIR / "sqlite"
PROCESSED_SCORES_DIR = DATA_DIR / "processed" / "scores"
REPORTS_SCORING_DIR = PROJECT_ROOT / "reports" / "scoring"
MANIFEST_PATH = DATA_DIR / "cache_manifest.json"
SQLITE_PATH = SQLITE_DIR / "market_120d.sqlite"
MODEL_VERSION = "1.0.0-mvp1"
INDEX_CODES = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"]

DAILY_FIELDS = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]
DAILY_BASIC_FIELDS = ["ts_code", "trade_date", "turnover_rate", "turnover_rate_f", "volume_ratio", "total_mv", "circ_mv"]
INDEX_DAILY_FIELDS = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]
STOCK_BASIC_FIELDS = ["ts_code", "symbol", "name", "area", "industry", "list_date"]
CLASSIFY_FIELDS = ["index_code", "industry_name", "level", "industry_code", "is_pub", "parent_code", "src"]
MEMBER_FIELDS = ["index_code", "index_name", "con_code", "con_name", "in_date", "out_date", "is_new"]


def ensure_dirs() -> None:
    for path in [
        RAW_DIR / "daily",
        RAW_DIR / "daily_basic",
        RAW_DIR / "index_daily",
        RAW_DIR / "stock_basic",
        RAW_DIR / "trade_cal",
        RAW_DIR / "index_classify",
        RAW_DIR / "index_member" / "SW2021_L2",
        SQLITE_DIR,
        PROCESSED_SCORES_DIR,
        REPORTS_SCORING_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def read_manifest() -> dict[str, Any]:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            broken_path = MANIFEST_PATH.with_suffix(".broken.json")
            try:
                shutil.copy2(MANIFEST_PATH, broken_path)
            except Exception:
                pass
            return {"updated_at": None, "items": {}}
    return {"updated_at": None, "items": {}}


def write_manifest(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = MANIFEST_PATH.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(MANIFEST_PATH)


def update_manifest_item(name: str, path: Path, status: str, rows: int, fields: list[str], source: str) -> None:
    manifest = read_manifest()
    manifest.setdefault("items", {})[name] = {
        "path": str(path.relative_to(PROJECT_ROOT)) if path.exists() or path.parent.exists() else str(path),
        "status": status,
        "rows": int(rows),
        "fields": fields,
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    write_manifest(manifest)


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype={"ts_code": "string", "trade_date": "string", "index_code": "string", "con_code": "string", "symbol": "string"})
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def csv_complete(path: Path, fields: list[str], min_rows: int = 1) -> bool:
    if not path.exists():
        return False
    try:
        df = read_csv(path)
    except Exception:
        return False
    return len(df) >= min_rows and all(field in df.columns for field in fields)


def code_file_part(ts_code: str) -> str:
    return ts_code.replace(".", "_")


def daily_path(date: str) -> Path:
    return RAW_DIR / "daily" / f"daily_{date}.csv"


def daily_basic_path(date: str) -> Path:
    return RAW_DIR / "daily_basic" / f"daily_basic_{date}.csv"


def index_daily_path(ts_code: str, date: str) -> Path:
    return RAW_DIR / "index_daily" / f"index_daily_{code_file_part(ts_code)}_{date}.csv"


def stock_basic_path() -> Path:
    return RAW_DIR / "stock_basic" / "stock_basic.csv"


def classify_path(level: str) -> Path:
    return RAW_DIR / "index_classify" / f"industry_classify_SW2021_{level}.csv"


def member_path(index_code: str) -> Path:
    return RAW_DIR / "index_member" / "SW2021_L2" / f"members_{code_file_part(index_code)}.csv"


def legacy_copy(src: Path, dst: Path, fields: list[str], min_rows: int = 1) -> bool:
    if csv_complete(dst, fields, min_rows=min_rows):
        return True
    if src.exists() and csv_complete(src, fields, min_rows=min_rows):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        df = read_csv(dst)
        update_manifest_item(dst.stem, dst, "cached_from_legacy", len(df), list(df.columns), "legacy_cache")
        return True
    return False


def available_daily_dates() -> list[str]:
    dates = set()
    for folder in [RAW_DIR / "daily", LEGACY_ROOT / "data" / "raw"]:
        if not folder.exists():
            continue
        for file in folder.glob("daily_*.csv"):
            stem = file.stem.replace("daily_", "")
            if stem.isdigit() and len(stem) == 8:
                dates.add(stem)
    return sorted(dates)


def fetch_open_trade_dates(pro: Any, end_date: str, window: int) -> list[str]:
    start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=max(window * 2, 240))).strftime("%Y%m%d")
    cal = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
    if cal is None or cal.empty:
        return []
    return sorted(str(value) for value in cal["cal_date"].astype(str).tolist())


def get_pro() -> Any | None:
    clear_bad_tushare_proxy()
    token = os.getenv("TUSHARE_TOKEN")
    if not token:
        print("TUSHARE_TOKEN: missing; using local cache only")
        return None
    print(f"TUSHARE_TOKEN: present length={len(token)}; full token is not printed")
    import tushare as ts
    return ts.pro_api(token)


def fetch_if_needed(pro: Any | None, name: str, path: Path, fields: list[str], fetcher, min_rows: int = 1) -> str:
    if csv_complete(path, fields, min_rows=min_rows):
        df = read_csv(path)
        update_manifest_item(name, path, "cache_hit", len(df), list(df.columns), "local_cache")
        return "cache_hit"
    if pro is None:
        update_manifest_item(name, path, "missing_offline_mode", 0, fields, "none")
        return "missing_offline_mode"

    last_error = ""
    for attempt in range(1, 4):
        try:
            time.sleep(0.6 * attempt)
            df = fetcher(pro)
            if df is None:
                df = pd.DataFrame(columns=fields)
            if len(df) < min_rows:
                status = "empty"
                update_manifest_item(name, path, status, len(df), list(df.columns), "tushare")
                if min_rows == 0:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    df.to_csv(path, index=False, encoding="utf-8-sig")
                return status
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(path.suffix + ".tmp")
            df.to_csv(tmp_path, index=False, encoding="utf-8-sig")
            tmp_path.replace(path)
            update_manifest_item(name, path, "fetched", len(df), list(df.columns), "tushare")
            return "fetched"
        except Exception as exc:
            last_error = str(exc)[:180]
            print(f"WARN {name}: fetch attempt {attempt}/3 failed: {last_error}")
    update_manifest_item(name, path, f"failed_after_retries: {last_error}", 0, fields, "tushare")
    return "failed_after_retries"

def prepare_static_caches(pro: Any | None) -> list[str]:
    statuses: list[str] = []
    legacy_copy(LEGACY_ROOT / "data" / "basic" / "stock_basic.csv", stock_basic_path(), STOCK_BASIC_FIELDS)
    statuses.append(fetch_if_needed(pro, "stock_basic", stock_basic_path(), STOCK_BASIC_FIELDS, lambda p: p.stock_basic(exchange="", list_status="L", fields=",".join(STOCK_BASIC_FIELDS))))

    for level in ["L1", "L2"]:
        legacy_copy(LEGACY_ROOT / "data" / "basic" / f"industry_classify_SW2021_{level}.csv", classify_path(level), CLASSIFY_FIELDS)
        statuses.append(fetch_if_needed(pro, f"index_classify_SW2021_{level}", classify_path(level), CLASSIFY_FIELDS, lambda p, lv=level: p.index_classify(level=lv, src="SW2021", fields=",".join(CLASSIFY_FIELDS))))

    l2 = read_csv(classify_path("L2")) if classify_path("L2").exists() else pd.DataFrame()
    for row in l2.itertuples(index=False):
        index_code = str(row.index_code)
        legacy_copy(LEGACY_ROOT / "data" / "basic" / "industry_members_L2" / f"members_{code_file_part(index_code)}.csv", member_path(index_code), MEMBER_FIELDS, min_rows=0)
        statuses.append(fetch_if_needed(pro, f"index_member_{index_code}", member_path(index_code), MEMBER_FIELDS, lambda p, code=index_code: p.index_member(index_code=code, fields=",".join(MEMBER_FIELDS)), min_rows=0))
    return statuses


def prepare_daily_caches(pro: Any | None, dates: list[str]) -> list[str]:
    statuses: list[str] = []
    for date in dates:
        legacy_copy(LEGACY_ROOT / "data" / "raw" / f"daily_{date}.csv", daily_path(date), DAILY_FIELDS)
        statuses.append(fetch_if_needed(pro, f"daily_{date}", daily_path(date), DAILY_FIELDS, lambda p, d=date: p.query("daily", trade_date=d, fields=",".join(DAILY_FIELDS))))

        legacy_copy(LEGACY_ROOT / "data" / "raw" / f"daily_basic_{date}.csv", daily_basic_path(date), ["ts_code", "trade_date", "turnover_rate", "total_mv", "circ_mv"])
        statuses.append(fetch_if_needed(pro, f"daily_basic_{date}", daily_basic_path(date), ["ts_code", "trade_date", "turnover_rate", "total_mv", "circ_mv"], lambda p, d=date: p.daily_basic(trade_date=d, fields=",".join(DAILY_BASIC_FIELDS))))

        for code in INDEX_CODES:
            dst = index_daily_path(code, date)
            if not csv_complete(dst, INDEX_DAILY_FIELDS):
                legacy_20d = LEGACY_ROOT / "data" / "raw" / f"index_daily_{code_file_part(code)}_20260630_20d.csv"
                if legacy_20d.exists():
                    df = read_csv(legacy_20d)
                    one = df[df["trade_date"].astype(str) == date].copy()
                    if len(one) > 0 and all(field in one.columns for field in INDEX_DAILY_FIELDS):
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        one.to_csv(dst, index=False, encoding="utf-8-sig")
                        update_manifest_item(f"index_daily_{code}_{date}", dst, "cached_from_legacy_20d", len(one), list(one.columns), "legacy_cache")
            statuses.append(fetch_if_needed(pro, f"index_daily_{code}_{date}", dst, INDEX_DAILY_FIELDS, lambda p, c=code, d=date: p.index_daily(ts_code=c, trade_date=d, fields=",".join(INDEX_DAILY_FIELDS))))
    return statuses


def standardize_daily(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["trade_date"] = out["trade_date"].astype(str)
    out["vol_shares"] = pd.to_numeric(out["vol"], errors="coerce") * 100
    out["amount_yuan"] = pd.to_numeric(out["amount"], errors="coerce") * 1000
    out["return"] = pd.to_numeric(out["pct_chg"], errors="coerce") / 100
    return out


def standardize_daily_basic(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["trade_date"] = out["trade_date"].astype(str)
    out["turnover_rate_decimal"] = pd.to_numeric(out.get("turnover_rate"), errors="coerce") / 100
    out["turnover_rate_f_decimal"] = pd.to_numeric(out.get("turnover_rate_f"), errors="coerce") / 100
    out["total_mv_yuan"] = pd.to_numeric(out.get("total_mv"), errors="coerce") * 10000
    out["circ_mv_yuan"] = pd.to_numeric(out.get("circ_mv"), errors="coerce") * 10000
    return out


def standardize_index_daily(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["trade_date"] = out["trade_date"].astype(str)
    out["vol_shares"] = pd.to_numeric(out.get("vol"), errors="coerce") * 100
    out["amount_yuan"] = pd.to_numeric(out.get("amount"), errors="coerce") * 1000
    out["return"] = pd.to_numeric(out.get("pct_chg"), errors="coerce") / 100
    return out


def replace_table(conn: sqlite3.Connection, table: str, df: pd.DataFrame) -> None:
    df.to_sql(table, conn, if_exists="replace", index=False)


def write_sqlite(dates: list[str]) -> dict[str, int]:
    SQLITE_DIR.mkdir(parents=True, exist_ok=True)
    daily_frames = [standardize_daily(read_csv(daily_path(d))) for d in dates if daily_path(d).exists()]
    daily_basic_frames = [standardize_daily_basic(read_csv(daily_basic_path(d))) for d in dates if daily_basic_path(d).exists() and not read_csv(daily_basic_path(d)).empty]
    index_frames = []
    for date in dates:
        for code in INDEX_CODES:
            p = index_daily_path(code, date)
            if p.exists():
                index_frames.append(standardize_index_daily(read_csv(p)))
    stock_basic = read_csv(stock_basic_path()) if stock_basic_path().exists() else pd.DataFrame(columns=STOCK_BASIC_FIELDS)
    classify_frames = [read_csv(classify_path(level)) for level in ["L1", "L2"] if classify_path(level).exists()]
    members = []
    member_dir = RAW_DIR / "index_member" / "SW2021_L2"
    if member_dir.exists():
        for file in member_dir.glob("members_*.csv"):
            df = read_csv(file)
            if len(df) > 0:
                members.append(df)

    tables = {
        "daily": pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame(columns=DAILY_FIELDS),
        "daily_basic": pd.concat(daily_basic_frames, ignore_index=True) if daily_basic_frames else pd.DataFrame(columns=DAILY_BASIC_FIELDS),
        "index_daily": pd.concat(index_frames, ignore_index=True) if index_frames else pd.DataFrame(columns=INDEX_DAILY_FIELDS),
        "stock_basic": stock_basic,
        "index_classify": pd.concat(classify_frames, ignore_index=True) if classify_frames else pd.DataFrame(columns=CLASSIFY_FIELDS),
        "index_member": pd.concat(members, ignore_index=True) if members else pd.DataFrame(columns=MEMBER_FIELDS),
    }
    with sqlite3.connect(SQLITE_PATH) as conn:
        key_map = {
            "daily": ["ts_code", "trade_date"],
            "daily_basic": ["ts_code", "trade_date"],
            "index_daily": ["ts_code", "trade_date"],
            "stock_basic": ["ts_code"],
            "index_classify": ["index_code"],
            "index_member": ["index_code", "con_code", "in_date"],
        }
        date_map = {
            "daily": "trade_date",
            "daily_basic": "trade_date",
            "index_daily": "trade_date",
            "stock_basic": None,
            "index_classify": None,
            "index_member": None,
        }
        for table, df in tables.items():
            if not df.empty:
                safe_merge_table(conn, table, df, key_map[table], date_map[table])
            elif not table_stats(conn, table, date_map[table])["exists"]:
                replace_table(conn, table, df)
        create_standard_indexes(conn)
        conn.commit()
        counts = {name: int(table_stats(conn, name, date_map[name])["rows"]) for name in tables}
    update_manifest_item("sqlite_market_120d", SQLITE_PATH, "written", sum(counts.values()), list(counts.keys()), "sqlite")
    return counts


def select_target_dates(end_date: str | None, window: int, pro: Any | None = None) -> list[str]:
    dates = available_daily_dates()
    if end_date and pro is not None:
        fetched = fetch_open_trade_dates(pro, end_date=end_date, window=window)
        if fetched:
            dates = sorted(set(dates).union(fetched))
    if end_date:
        dates = [d for d in dates if d <= end_date]
    return dates[-window:]


def run_update(end_date: str | None = None, window: int = 120, use_api: bool = True) -> dict[str, Any]:
    ensure_dirs()
    pro = get_pro() if use_api else None
    prepare_static_caches(pro)
    dates = select_target_dates(end_date, window, pro)
    if not dates:
        raise RuntimeError("No daily cache dates available and trade calendar fetching is not implemented for empty cache in MVP.")
    prepare_daily_caches(pro, dates)
    counts = write_sqlite(dates)
    result = {
        "sqlite_path": str(SQLITE_PATH),
        "dates": dates,
        "table_counts": counts,
        "manifest_path": str(MANIFEST_PATH),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--window", type=int, default=120)
    parser.add_argument("--online", action="store_true", help="allow Tushare network calls for missing cache")
    parser.add_argument("--no-api", action="store_true", help="force local cache only")
    args = parser.parse_args()
    use_api = bool(args.online and not args.no_api)
    if not use_api:
        print("Update mode: offline cache only. Use --online to fetch missing Tushare data.")
    run_update(args.end_date, args.window, use_api=use_api)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())




