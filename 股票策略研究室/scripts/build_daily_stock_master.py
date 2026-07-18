"""Build daily stock master table from cached Tushare files.

Stage 2 uses existing cache only:
- data/raw/daily_YYYYMMDD.csv
- data/basic/stock_basic.csv
- data/raw/daily_basic_YYYYMMDD.csv
- data/basic/index_basic_SSE.csv
- data/raw/index_daily_000001_SH_YYYYMMDD.csv

No token access and no API calls.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"
BASIC_DIR = PROJECT_ROOT / "data" / "basic"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"

STRING_DTYPES = {
    "ts_code": "string",
    "symbol": "string",
    "trade_date": "string",
    "list_date": "string",
}

MASTER_FIELDS = [
    "ts_code",
    "symbol",
    "name",
    "area",
    "industry",
    "list_date",
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
    "turnover_rate",
    "volume_ratio",
    "pe",
    "pb",
    "total_mv",
    "circ_mv",
]

INDEX_NAMES = ["上证指数", "深证成指", "创业板指", "科创50", "沪深300", "中证1000", "中证2000"]


def read_csv_safe(path: Path) -> pd.DataFrame:
    dtype = {key: value for key, value in STRING_DTYPES.items()}
    return pd.read_csv(path, dtype=dtype, keep_default_na=False, na_values=["", "NA", "NaN", "nan"])


def symbol_from_ts_code(ts_code: str) -> str:
    return str(ts_code).split(".")[0].zfill(6)


def repair_symbol(df: pd.DataFrame) -> pd.DataFrame:
    if "ts_code" not in df.columns:
        raise ValueError("缺少ts_code字段")
    out = df.copy()
    if "symbol" not in out.columns:
        out["symbol"] = out["ts_code"].map(symbol_from_ts_code)
    else:
        out["symbol"] = out.apply(
            lambda row: symbol_from_ts_code(row["ts_code"])
            if pd.isna(row["symbol"]) or len(str(row["symbol"]).split(".")[0]) != 6
            else str(row["symbol"]).split(".")[0].zfill(6),
            axis=1,
        )
    out["ts_code"] = out["ts_code"].astype("string")
    out["symbol"] = out["symbol"].astype("string")
    return out


def load_inputs(date: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = repair_symbol(read_csv_safe(RAW_DIR / f"daily_{date}.csv"))
    stock_basic = repair_symbol(read_csv_safe(BASIC_DIR / "stock_basic.csv"))
    daily_basic = repair_symbol(read_csv_safe(RAW_DIR / f"daily_basic_{date}.csv"))
    index_basic_path = BASIC_DIR / "index_basic_SSE.csv"
    index_basic = read_csv_safe(index_basic_path) if index_basic_path.exists() else pd.DataFrame()
    return daily, stock_basic, daily_basic, index_basic


def duplicate_key_count(df: pd.DataFrame, keys: list[str]) -> int:
    if not all(key in df.columns for key in keys):
        return 0
    return int(df.duplicated(subset=keys).sum())


def build_master(date: str) -> tuple[pd.DataFrame, dict[str, object], pd.DataFrame]:
    daily, stock_basic, daily_basic, index_basic = load_inputs(date)

    daily_rows = len(daily)
    stock_rows = len(stock_basic)
    daily_basic_rows = len(daily_basic)

    daily_keys = set(daily["ts_code"].astype(str))
    daily_basic_keys = set(daily_basic["ts_code"].astype(str))
    daily_only = sorted(daily_keys - daily_basic_keys)
    daily_basic_only = sorted(daily_basic_keys - daily_keys)

    stock_cols = [col for col in ["ts_code", "symbol", "name", "area", "industry", "list_date"] if col in stock_basic.columns]
    daily_basic_cols = [col for col in ["ts_code", "trade_date", "turnover_rate", "volume_ratio", "pe", "pb", "total_mv", "circ_mv"] if col in daily_basic.columns]

    master = daily.merge(stock_basic[stock_cols], on="ts_code", how="left", suffixes=("", "_stock"))
    if "symbol_stock" in master.columns:
        master["symbol"] = master["symbol"].where(master["symbol"].notna(), master["symbol_stock"])
        master = master.drop(columns=["symbol_stock"])
    master = master.merge(daily_basic[daily_basic_cols], on=["ts_code", "trade_date"], how="left", suffixes=("", "_daily_basic"))

    for field in MASTER_FIELDS:
        if field not in master.columns:
            master[field] = pd.NA
    master = repair_symbol(master[MASTER_FIELDS])

    name_matches = int(master["name"].notna().sum())
    db_matches = int(master["turnover_rate"].notna().sum())
    quality = {
        "date": date,
        "daily_rows": daily_rows,
        "stock_basic_rows": stock_rows,
        "daily_basic_rows": daily_basic_rows,
        "name_match_count": name_matches,
        "name_match_rate": name_matches / daily_rows if daily_rows else 0,
        "daily_basic_match_count": db_matches,
        "daily_basic_match_rate": db_matches / daily_rows if daily_rows else 0,
        "daily_only_codes": daily_only,
        "daily_basic_only_codes": daily_basic_only,
        "daily_duplicate_keys": duplicate_key_count(daily, ["ts_code", "trade_date"]),
        "daily_basic_duplicate_keys": duplicate_key_count(daily_basic, ["ts_code", "trade_date"]),
        "master_duplicate_keys": duplicate_key_count(master, ["ts_code", "trade_date"]),
        "missing_counts": {field: int(master[field].isna().sum()) for field in master.columns},
    }
    return master, quality, index_basic


def find_index_coverage(index_basic: pd.DataFrame) -> list[dict[str, str]]:
    if index_basic.empty or "name" not in index_basic.columns or "ts_code" not in index_basic.columns:
        return [{"name": name, "status": "当前指数名册未覆盖", "ts_code": ""} for name in INDEX_NAMES]
    rows = []
    for name in INDEX_NAMES:
        matched = index_basic[index_basic["name"].astype(str) == name]
        if len(matched) == 0:
            rows.append({"name": name, "status": "当前指数名册未覆盖", "ts_code": ""})
        else:
            rows.append({"name": name, "status": "已覆盖", "ts_code": str(matched.iloc[0]["ts_code"])})
    return rows


def top_amount(master: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    return master.sort_values("amount", ascending=False).head(n)[["name", "ts_code", "pct_chg", "amount"]]


def top_total_mv(master: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    return master.sort_values("total_mv", ascending=False).head(n)[["name", "ts_code", "total_mv", "pct_chg"]]


def top_turnover(master: pd.DataFrame, n: int = 20, min_amount: float = 100000) -> pd.DataFrame:
    filtered = master[master["amount"] >= min_amount]
    return filtered.sort_values("turnover_rate", ascending=False).head(n)[["name", "ts_code", "turnover_rate", "amount", "pct_chg"]]


def critical_missing(master: pd.DataFrame) -> pd.DataFrame:
    fields = ["ts_code", "symbol", "name", "trade_date", "close", "pct_chg", "amount", "turnover_rate"]
    missing_mask = master[fields].isna().any(axis=1)
    return master.loc[missing_mask, fields]


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "无"
    cols = [str(col) for col in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join(["---"] * len(cols)) + " |"]
    for row in df.itertuples(index=False, name=None):
        values = []
        for value in row:
            if isinstance(value, float):
                values.append(f"{value:.4f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def write_report(date: str, master: pd.DataFrame, quality: dict[str, object], index_basic: pd.DataFrame) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"daily_stock_master_quality_{date}.md"
    index_coverage = pd.DataFrame(find_index_coverage(index_basic))
    missing_counts = pd.DataFrame(
        [{"field": field, "missing_count": count} for field, count in quality["missing_counts"].items()]
    )
    daily_only = quality["daily_only_codes"]
    daily_basic_only = quality["daily_basic_only_codes"]
    lines = [
        f"# 每日股票基础总表质量报告 {date}",
        "",
        "## 1. 合并质量检查",
        f"- daily原始行数：{quality['daily_rows']}",
        f"- stock_basic原始行数：{quality['stock_basic_rows']}",
        f"- daily_basic原始行数：{quality['daily_basic_rows']}",
        f"- 成功匹配股票名称数量：{quality['name_match_count']}，匹配率：{quality['name_match_rate']:.2%}",
        f"- 成功匹配daily_basic数量：{quality['daily_basic_match_count']}，匹配率：{quality['daily_basic_match_rate']:.2%}",
        f"- daily独有代码数量：{len(daily_only)}",
        f"- daily_basic独有代码数量：{len(daily_basic_only)}",
        f"- daily重复主键：{quality['daily_duplicate_keys']}",
        f"- daily_basic重复主键：{quality['daily_basic_duplicate_keys']}",
        f"- master重复主键：{quality['master_duplicate_keys']}",
        "",
        "## 2. 缺失字段统计",
        markdown_table(missing_counts),
        "",
        "## 3. 指数名册覆盖检查",
        markdown_table(index_coverage),
        "",
        "## 4. 成交额前20股票",
        markdown_table(top_amount(master)),
        "",
        "## 5. 总市值前20股票",
        markdown_table(top_total_mv(master)),
        "",
        "## 6. 换手率前20股票（排除成交额过低样本）",
        markdown_table(top_turnover(master)),
        "",
        "## 7. 缺失关键字段股票清单",
        markdown_table(critical_missing(master).head(100)),
        "",
        "## 8. 差异代码样例",
        "- daily独有代码样例：" + ", ".join(daily_only[:50]) if daily_only else "- daily独有代码样例：无",
        "- daily_basic独有代码样例：" + ", ".join(daily_basic_only[:50]) if daily_basic_only else "- daily_basic独有代码样例：无",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run(date: str) -> dict[str, object]:
    master, quality, index_basic = build_master(date)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / f"daily_stock_master_{date}.csv"
    master.to_csv(out_path, index=False, encoding="utf-8-sig")
    report_path = write_report(date, master, quality, index_basic)
    return {"master": master, "quality": quality, "out_path": out_path, "report_path": report_path}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="20260630")
    args = parser.parse_args()
    result = run(args.date)
    quality = result["quality"]
    print(f"总表行数: {len(result['master'])}")
    print(f"名称匹配率: {quality['name_match_rate']:.2%}")
    print(f"daily_basic匹配率: {quality['daily_basic_match_rate']:.2%}")
    print(f"daily独有代码数量: {len(quality['daily_only_codes'])}")
    print(f"daily_basic独有代码数量: {len(quality['daily_basic_only_codes'])}")
    print(f"输出总表: {result['out_path']}")
    print(f"输出报告: {result['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
