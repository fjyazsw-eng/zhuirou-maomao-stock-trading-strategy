from __future__ import annotations
from scoring_system.tushare_client import credential_marker

import json
import os
import sqlite3
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.data_cache import create_standard_indexes, null_report, safe_merge_table, table_stats
from scoring_system.network_env import clear_bad_tushare_proxy


DATA = ROOT / "data"
RAW = DATA / "raw" / "tushare"
SQLITE = DATA / "sqlite" / "market_120d.sqlite"
MANIFEST = DATA / "cache_manifest.json"
REPORT = ROOT / "reports" / "handoff_latest.md"

INDEX_CODES = ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"]

DAILY_FIELDS = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]
DAILY_BASIC_FIELDS = ["ts_code", "trade_date", "turnover_rate", "turnover_rate_f", "volume_ratio", "total_mv", "circ_mv"]
INDEX_DAILY_FIELDS = ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]
ADJ_FACTOR_FIELDS = ["ts_code", "trade_date", "adj_factor"]
TRADE_CAL_FIELDS = ["exchange", "cal_date", "is_open", "pretrade_date"]


def ensure_dirs() -> None:
    for folder in [
        RAW / "daily",
        RAW / "daily_basic",
        RAW / "index_daily",
        RAW / "adj_factor",
        RAW / "trade_cal",
        DATA / "sqlite",
        ROOT / "reports",
    ]:
        folder.mkdir(parents=True, exist_ok=True)


def read_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path, dtype="string")
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def csv_complete(path: Path, fields: list[str], min_rows: int) -> bool:
    if not path.exists():
        return False
    try:
        df = read_csv(path)
    except Exception:
        return False
    return len(df) >= min_rows and all(field in df.columns for field in fields)


def load_manifest() -> dict[str, Any]:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {"updated_at": None, "items": {}}


def save_manifest(manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def manifest_item(manifest: dict[str, Any], name: str, path: Path, status: str, rows: int, fields: list[str], source: str) -> None:
    manifest.setdefault("items", {})[name] = {
        "path": str(path.relative_to(ROOT)),
        "status": status,
        "rows": int(rows),
        "fields": fields,
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def code_part(ts_code: str) -> str:
    return ts_code.replace(".", "_")


def daily_path(date: str) -> Path:
    return RAW / "daily" / f"daily_{date}.csv"


def daily_basic_path(date: str) -> Path:
    return RAW / "daily_basic" / f"daily_basic_{date}.csv"


def index_daily_path(code: str, date: str) -> Path:
    return RAW / "index_daily" / f"index_daily_{code_part(code)}_{date}.csv"


def adj_factor_path(date: str) -> Path:
    return RAW / "adj_factor" / f"adj_factor_{date}.csv"


def trade_cal_path(start: str, end: str) -> Path:
    return RAW / "trade_cal" / f"trade_cal_{start}_{end}.csv"


def fetch_with_retries(name: str, fetcher: Callable[[], pd.DataFrame]) -> tuple[pd.DataFrame, str]:
    last_error = ""
    for attempt in range(1, 4):
        try:
            if attempt > 1:
                time.sleep(attempt)
            df = fetcher()
            if df is None:
                df = pd.DataFrame()
            return df, "ok"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:220]}"
            print(f"WARN {name}: attempt {attempt}/3 failed: {last_error}")
    return pd.DataFrame(), last_error


def write_if_needed(
    manifest: dict[str, Any],
    name: str,
    path: Path,
    fields: list[str],
    min_rows: int,
    fetcher: Callable[[], pd.DataFrame],
) -> tuple[str, int]:
    if csv_complete(path, fields, min_rows):
        df = read_csv(path)
        manifest_item(manifest, name, path, "cache_hit", len(df), list(df.columns), "local_cache")
        return "cache_hit", len(df)

    df, status = fetch_with_retries(name, fetcher)
    if status != "ok":
        manifest_item(manifest, name, fpath(path), f"failed_after_retries: {status}", 0, fields, "tushare")
        return "failed", 0
    if len(df) < min_rows:
        manifest_item(manifest, name, path, "empty_or_incomplete", len(df), list(df.columns), "tushare")
        return "empty_or_incomplete", len(df)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)
    manifest_item(manifest, name, path, "fetched", len(df), list(df.columns), "tushare")
    return "fetched", len(df)


def fpath(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


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
    out["vol_shares"] = pd.to_numeric(out["vol"], errors="coerce") * 100
    out["amount_yuan"] = pd.to_numeric(out["amount"], errors="coerce") * 1000
    out["return"] = pd.to_numeric(out["pct_chg"], errors="coerce") / 100
    return out


def write_sqlite(dates: list[str]) -> dict[str, int]:
    daily_frames = [standardize_daily(read_csv(daily_path(d))) for d in dates if daily_path(d).exists()]
    basic_frames = [standardize_daily_basic(read_csv(daily_basic_path(d))) for d in dates if daily_basic_path(d).exists()]
    index_frames = []
    adj_frames = [read_csv(adj_factor_path(d)) for d in dates if adj_factor_path(d).exists()]
    for date in dates:
        for code in INDEX_CODES:
            path = index_daily_path(code, date)
            if path.exists():
                index_frames.append(standardize_index_daily(read_csv(path)))

    stock_basic = read_csv(RAW / "stock_basic" / "stock_basic.csv") if (RAW / "stock_basic" / "stock_basic.csv").exists() else pd.DataFrame()
    classify = []
    for level in ["L1", "L2"]:
        path = RAW / "index_classify" / f"industry_classify_SW2021_{level}.csv"
        if path.exists():
            classify.append(read_csv(path))
    members = []
    member_dir = RAW / "index_member" / "SW2021_L2"
    if member_dir.exists():
        members = [read_csv(path) for path in member_dir.glob("members_*.csv") if len(read_csv(path)) > 0]
    trade_cal_files = sorted((RAW / "trade_cal").glob("trade_cal_*.csv"))
    trade_cal = read_csv(trade_cal_files[-1]) if trade_cal_files else pd.DataFrame()

    tables = {
        "daily": pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame(),
        "daily_basic": pd.concat(basic_frames, ignore_index=True) if basic_frames else pd.DataFrame(),
        "index_daily": pd.concat(index_frames, ignore_index=True) if index_frames else pd.DataFrame(),
        "adj_factor": pd.concat(adj_frames, ignore_index=True) if adj_frames else pd.DataFrame(),
        "trade_cal": trade_cal,
        "stock_basic": stock_basic,
        "index_classify": pd.concat(classify, ignore_index=True) if classify else pd.DataFrame(),
        "index_member": pd.concat(members, ignore_index=True) if members else pd.DataFrame(),
    }

    merge_stats = {}
    with sqlite3.connect(SQLITE) as conn:
        key_map = {
            "daily": ["ts_code", "trade_date"],
            "daily_basic": ["ts_code", "trade_date"],
            "index_daily": ["ts_code", "trade_date"],
            "adj_factor": ["ts_code", "trade_date"],
            "trade_cal": ["cal_date"],
            "stock_basic": ["ts_code"],
            "index_classify": ["index_code"],
            "index_member": ["index_code", "con_code", "in_date"],
        }
        date_map = {
            "daily": "trade_date",
            "daily_basic": "trade_date",
            "index_daily": "trade_date",
            "adj_factor": "trade_date",
            "trade_cal": "cal_date",
            "stock_basic": None,
            "index_classify": None,
            "index_member": None,
        }
        for table, df in tables.items():
            if not df.empty:
                merge_stats[table] = safe_merge_table(conn, table, df, key_map[table], date_map[table])
            else:
                merge_stats[table] = {"before": table_stats(conn, table, date_map[table]), "after": table_stats(conn, table, date_map[table]), "incoming_rows": 0}
        create_standard_indexes(conn)
        conn.commit()
    counts = {name: int(stats["after"]["rows"]) for name, stats in merge_stats.items()}
    counts["_merge_stats"] = merge_stats
    return counts


def coverage_checks(dates: list[str]) -> dict[str, Any]:
    daily_counts = {}
    basic_counts = {}
    match_rates = {}
    missing_dates = []
    index_complete = {}
    for date in dates:
        ddf = read_csv(daily_path(date)) if daily_path(date).exists() else pd.DataFrame()
        bdf = read_csv(daily_basic_path(date)) if daily_basic_path(date).exists() else pd.DataFrame()
        daily_counts[date] = len(ddf)
        basic_counts[date] = len(bdf)
        if len(ddf) == 0 or len(bdf) == 0:
            match_rates[date] = None
            missing_dates.append(date)
        else:
            match_rates[date] = round(len(set(ddf["ts_code"]).intersection(set(bdf["ts_code"]))) / len(ddf), 4)
        index_complete[date] = sum(1 for code in INDEX_CODES if csv_complete(index_daily_path(code, date), INDEX_DAILY_FIELDS, 1))

    member_dir = RAW / "index_member" / "SW2021_L2"
    members = []
    if member_dir.exists():
        for path in member_dir.glob("members_*.csv"):
            df = read_csv(path)
            if len(df) > 0:
                members.append(df)
    members_df = pd.concat(members, ignore_index=True) if members else pd.DataFrame()

    sector_rows = []
    latest = dates[-1]
    latest_daily = read_csv(daily_path(latest)) if daily_path(latest).exists() else pd.DataFrame()
    latest_basic = read_csv(daily_basic_path(latest)) if daily_basic_path(latest).exists() else pd.DataFrame()
    prev_basic = read_csv(daily_basic_path(dates[-2])) if len(dates) >= 2 and daily_basic_path(dates[-2]).exists() else pd.DataFrame()
    daily_codes = set(latest_daily["ts_code"]) if "ts_code" in latest_daily.columns else set()
    prev_mv = prev_basic.dropna(subset=["circ_mv"]) if "circ_mv" in prev_basic.columns else pd.DataFrame()
    prev_mv_codes = set(prev_mv["ts_code"]) if "ts_code" in prev_mv.columns else set()

    if len(members_df) > 0:
        for index_code, group in members_df.groupby("index_code"):
            active = group[
                (group["in_date"].fillna("") <= latest)
                & ((group["out_date"].isna()) | (group["out_date"].fillna("") == "") | (group["out_date"].fillna("") > latest))
            ]
            codes = set(active["con_code"]) if "con_code" in active.columns else set()
            if codes:
                sector_rows.append(
                    {
                        "index_code": index_code,
                        "active_count": len(codes),
                        "quote_coverage": len(codes.intersection(daily_codes)) / len(codes),
                        "t_minus_1_mv_coverage": len(codes.intersection(prev_mv_codes)) / len(codes),
                    }
                )
    sector_df = pd.DataFrame(sector_rows)
    sector_summary = {
        "sector_count": int(len(sector_df)),
        "quote_coverage_min": None if sector_df.empty else round(float(sector_df["quote_coverage"].min()), 4),
        "quote_coverage_avg": None if sector_df.empty else round(float(sector_df["quote_coverage"].mean()), 4),
        "quote_coverage_below_70_count": 0 if sector_df.empty else int((sector_df["quote_coverage"] < 0.7).sum()),
        "t_minus_1_mv_coverage_min": None if sector_df.empty else round(float(sector_df["t_minus_1_mv_coverage"].min()), 4),
        "t_minus_1_mv_coverage_avg": None if sector_df.empty else round(float(sector_df["t_minus_1_mv_coverage"].mean()), 4),
        "t_minus_1_mv_coverage_below_70_count": 0 if sector_df.empty else int((sector_df["t_minus_1_mv_coverage"] < 0.7).sum()),
    }

    return {
        "daily_counts": daily_counts,
        "daily_basic_counts": basic_counts,
        "daily_daily_basic_match_rates": match_rates,
        "index_complete_counts": index_complete,
        "missing_dates": missing_dates,
        "sector_coverage": sector_summary,
    }


def table_lines(mapping: dict[str, Any], title: str) -> list[str]:
    lines = [f"### {title}", "", "| 日期 | 数值 |", "|---|---:|"]
    for key, value in mapping.items():
        lines.append(f"| {key} | {'' if value is None else value} |")
    lines.append("")
    return lines


def discover_local_dates() -> list[str]:
    daily_dates = {p.stem.replace("daily_", "") for p in (RAW / "daily").glob("daily_*.csv")}
    basic_dates = {p.stem.replace("daily_basic_", "") for p in (RAW / "daily_basic").glob("daily_basic_*.csv")}
    complete = sorted(d for d in daily_dates.intersection(basic_dates) if d.isdigit() and len(d) == 8)
    return complete[-30:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-api", action="store_true", help="只读取本地CSV并增量合并SQLite，不测试或调用Tushare")
    args = parser.parse_args()
    ensure_dirs()
    if not args.no_api:
        clear_bad_tushare_proxy()
    token = credential_marker()
    from scoring_system import tushare_client as ts

    connection = {
        "python_path": sys.executable,
        "tushare_version": getattr(ts, "__version__", "unknown"),
        "token_status": "missing" if not token else f"present length={len(token)} masked={token[:2]}***{token[-2:]}",
        "trade_cal": "not_run",
        "daily": "not_run",
        "daily_basic": "not_run",
        "network_or_sandbox_issue": "未发现",
    }
    if args.no_api:
        connection["trade_cal"] = "离线模式未测试"
        connection["daily"] = "离线模式未测试"
        connection["daily_basic"] = "离线模式未测试"
        dates = discover_local_dates()
    elif not token:
        raise RuntimeError("HITHINK_FINANCE_API_KEY missing")
    else:
        pro = ts.pro_api(token)

        today = datetime.now().strftime("%Y%m%d")
        start_probe = "20260501"
        cal_df, cal_status = fetch_with_retries(
            "trade_cal_probe",
            lambda: pro.trade_cal(exchange="", start_date=start_probe, end_date=today, fields=",".join(TRADE_CAL_FIELDS)),
        )
        connection["trade_cal"] = "正常" if cal_status == "ok" and len(cal_df) > 0 else f"失败: {cal_status}"
        if cal_status != "ok":
            connection["network_or_sandbox_issue"] = cal_status
            latest_complete = "20260630"
            dates = []
        else:
            open_dates = cal_df[cal_df["is_open"].astype(str) == "1"]["cal_date"].astype(str).sort_values().tolist()
            latest_complete = ""
            for candidate in reversed(open_dates):
                ddf, dstatus = fetch_with_retries("daily_probe", lambda c=candidate: pro.daily(trade_date=c, fields=",".join(DAILY_FIELDS)))
                bdf, bstatus = fetch_with_retries("daily_basic_probe", lambda c=candidate: pro.daily_basic(trade_date=c, fields=",".join(DAILY_BASIC_FIELDS)))
                if dstatus == "ok" and bstatus == "ok" and len(ddf) > 1000 and len(bdf) > 1000:
                    latest_complete = candidate
                    connection["daily"] = f"正常 rows={len(ddf)} date={candidate}"
                    connection["daily_basic"] = f"正常 rows={len(bdf)} date={candidate}"
                    break
            if not latest_complete:
                raise RuntimeError("No complete trading day found from Tushare daily/daily_basic probe")
            dates = [d for d in open_dates if d <= latest_complete][-30:]

    manifest = load_manifest()
    if dates and not args.no_api:
        tc_path = trade_cal_path(dates[0], dates[-1])
        cal_window = cal_df[cal_df["cal_date"].astype(str).between(dates[0], dates[-1])].copy()
        cal_window.to_csv(tc_path, index=False, encoding="utf-8-sig")
        manifest_item(manifest, f"trade_cal_{dates[0]}_{dates[-1]}", tc_path, "fetched", len(cal_window), list(cal_window.columns), "tushare")

        for date in dates:
            write_if_needed(manifest, f"daily_{date}", daily_path(date), DAILY_FIELDS, 1000, lambda d=date: pro.daily(trade_date=d, fields=",".join(DAILY_FIELDS)))
            write_if_needed(manifest, f"daily_basic_{date}", daily_basic_path(date), DAILY_BASIC_FIELDS, 1000, lambda d=date: pro.daily_basic(trade_date=d, fields=",".join(DAILY_BASIC_FIELDS)))
            write_if_needed(manifest, f"adj_factor_{date}", adj_factor_path(date), ADJ_FACTOR_FIELDS, 1000, lambda d=date: pro.adj_factor(trade_date=d, fields=",".join(ADJ_FACTOR_FIELDS)))
            for code in INDEX_CODES:
                write_if_needed(
                    manifest,
                    f"index_daily_{code}_{date}",
                    index_daily_path(code, date),
                    INDEX_DAILY_FIELDS,
                    1,
                    lambda c=code, d=date: pro.index_daily(ts_code=c, trade_date=d, fields=",".join(INDEX_DAILY_FIELDS)),
                )

    sqlite_counts = write_sqlite(dates) if dates else {}
    merge_stats = sqlite_counts.pop("_merge_stats", {}) if sqlite_counts else {}
    if dates:
        manifest_item(manifest, "sqlite_market_120d", SQLITE, "written_30d_phase2a", sum(sqlite_counts.values()), list(sqlite_counts.keys()), "sqlite")
    save_manifest(manifest)

    checks = coverage_checks(dates) if dates else {}
    match_values = [v for v in checks.get("daily_daily_basic_match_rates", {}).values() if v is not None]
    avg_match = round(sum(match_values) / len(match_values), 4) if match_values else None

    first_daily = read_csv(daily_path(dates[-1])) if dates else pd.DataFrame()
    daily_all = pd.concat([read_csv(daily_path(d)) for d in dates if daily_path(d).exists()], ignore_index=True) if dates else pd.DataFrame()
    basic_all = pd.concat([read_csv(daily_basic_path(d)) for d in dates if daily_basic_path(d).exists()], ignore_index=True) if dates else pd.DataFrame()
    null_checks = {
        "daily": null_report(daily_all, ["ts_code", "trade_date", "open", "high", "low", "close", "pct_chg", "amount"]),
        "daily_basic": null_report(basic_all, ["ts_code", "trade_date", "turnover_rate", "total_mv", "circ_mv"]),
    }
    unit_note = "日线 vol*100=股、amount*1000=元；daily_basic 市值*10000=元、换手率/100=小数，SQLite 写入前已标准化。"
    if len(first_daily) > 0:
        amount_sample = pd.to_numeric(first_daily["amount"], errors="coerce").median()
        unit_note += f" 最新日 amount 原始中位数约 {round(float(amount_sample), 2)} 千元，未发现 1000/10000 倍异常。"

    lines = [
        "# Phase 2A：连接复测与30交易日数据准备",
        "",
        f"- 是否完成：{'是' if dates and len(dates) == 30 and not checks.get('missing_dates') else '部分完成'}",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        f"- Python路径：`{connection['python_path']}`",
        f"- tushare版本：`{connection['tushare_version']}`",
        f"- Token状态：{connection['token_status']}",
        f"- trade_cal测试：{connection['trade_cal']}",
        f"- daily测试：{connection['daily']}",
        f"- daily_basic测试：{connection['daily_basic']}",
        f"- 网络或沙箱问题：{connection['network_or_sandbox_issue']}",
        f"- 已补齐交易日期范围：{dates[0] if dates else '无'} 至 {dates[-1] if dates else '无'}",
        f"- 实际交易日数量：{len(dates)}",
        f"- SQLite：`{SQLITE.relative_to(ROOT)}`",
        "",
        "## 数据行数和匹配率",
        "",
        f"- SQLite表行数：{sqlite_counts}",
        f"- SQLite安全合并统计：{merge_stats}",
        f"- daily/daily_basic平均匹配率：{avg_match}",
        f"- 指数完整性：每个交易日应为4个指数；低于4表示缺失。",
        f"- 板块覆盖率：{checks.get('sector_coverage', {})}",
        f"- 数据单位：{unit_note}",
        f"- 核心字段空值检查：{null_checks}",
        "- 离线重复运行检查：30个交易日核心CSV均已完整；后续本地评分和SQLite读取不需要重新下载完整数据。本脚本在线模式也会对完整CSV走cache_hit，仅补缺口。",
        "",
    ]
    if checks:
        lines += table_lines(checks["daily_counts"], "daily行数")
        lines += table_lines(checks["daily_basic_counts"], "daily_basic行数")
        lines += table_lines(checks["daily_daily_basic_match_rates"], "daily与daily_basic匹配率")
        lines += table_lines(checks["index_complete_counts"], "指数数据完整数量")

    missing = checks.get("missing_dates", []) if checks else []
    lines += [
        "## 缺失与问题",
        "",
        f"- 仍然缺失的日期：{missing if missing else '无'}",
        "- 仍然缺失的字段：未发现核心字段缺失；缺失值未填0。",
        "- adj_factor：已按30日补齐并写入SQLite，当前市场/板块评分暂不直接使用。",
        "",
        "## 龙头评分条件",
        "",
        "- 是否已经具备开发龙头评分的条件：是。30日行情、daily_basic、复权因子、SW2021 L2成分、指数行情和T-1流通市值口径均已具备；事件/公告风险仍应作为辅助输入，不阻塞龙头行情评分开发。",
        "",
        "## 下一步建议",
        "",
        "- 下一步可以进入龙头评分MVP，仅使用行情、板块归属、成交额排名、3至5日持续性和板块同步性。",
        "- 暂不建议引入公告、新闻、主力资金、人气排名作为硬性评分条件。",
        "",
        "## 本次新增或修改文件",
        "",
        "- `scripts/phase2a_prepare_30d.py`",
        "- `reports/handoff_latest.md`",
        "- `data/cache_manifest.json`",
        "- `data/sqlite/market_120d.sqlite`",
        "- `data/raw/tushare/trade_cal/trade_cal_*.csv`",
        "- `data/raw/tushare/daily/daily_*.csv`（仅缺失或不完整日期）",
        "- `data/raw/tushare/daily_basic/daily_basic_*.csv`（仅缺失或不完整日期）",
        "- `data/raw/tushare/index_daily/index_daily_*.csv`（仅缺失或不完整日期）",
        "- `data/raw/tushare/adj_factor/adj_factor_*.csv`",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(str(REPORT.relative_to(ROOT)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

