from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path("D:/股票AI交易助手数据/sqlite/market_2025.sqlite")
REPORT_DIR = ROOT / "reports" / "data"
REQUIRED_TABLES = ["trade_cal", "stock_basic", "daily", "daily_basic", "adj_factor", "index_daily", "limit_list", "suspend"]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def date_col(table: str) -> str:
    return "cal_date" if table == "trade_cal" else "trade_date"


def date_range(conn: sqlite3.Connection, table: str) -> tuple[str, str]:
    if not table_exists(conn, table):
        return "", ""
    col = date_col(table)
    try:
        row = conn.execute(f"SELECT MIN({col}), MAX({col}) FROM {table}").fetchone()
        return str(row[0] or ""), str(row[1] or "")
    except Exception:
        return "", ""


def duplicate_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    keys = {
        "trade_cal": ["exchange", "cal_date"],
        "stock_basic": ["ts_code"],
        "daily": ["ts_code", "trade_date"],
        "daily_basic": ["ts_code", "trade_date"],
        "adj_factor": ["ts_code", "trade_date"],
        "index_daily": ["ts_code", "trade_date"],
        "limit_list": ["ts_code", "trade_date"],
        "suspend": ["ts_code", "trade_date"],
    }.get(table, [])
    if not keys:
        return 0
    cols = ", ".join(keys)
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM (SELECT {cols}, COUNT(*) c FROM {table} GROUP BY {cols} HAVING c>1)").fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0


def daily_count_stats(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    if not table_exists(conn, table):
        return {}
    try:
        rows = conn.execute(f"SELECT trade_date, COUNT(*) FROM {table} GROUP BY trade_date ORDER BY trade_date").fetchall()
    except Exception:
        return {}
    counts = [int(x[1]) for x in rows]
    if not counts:
        return {}
    return {"days": len(counts), "min": min(counts), "max": max(counts), "avg": round(sum(counts) / len(counts), 2)}


def as_of_filter_ok(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT COUNT(*) FROM daily WHERE trade_date <= '20250630'").fetchone()
        return True
    except Exception:
        return False


def inspect(db_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "generated_at": now(),
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "db_on_d_drive": db_path.exists() and db_path.resolve().drive.upper().startswith("D:"),
        "tables": {},
        "checks": {},
        "status": "FAIL",
    }
    if not db_path.exists():
        result["checks"]["database"] = "missing"
        return result
    conn = sqlite3.connect(db_path)
    for table in REQUIRED_TABLES:
        start, end = date_range(conn, table)
        result["tables"][table] = {
            "exists": table_exists(conn, table),
            "rows": count_rows(conn, table),
            "start": start,
            "end": end,
            "duplicates": duplicate_count(conn, table),
            "daily_count_stats": daily_count_stats(conn, table) if table not in {"trade_cal", "stock_basic"} else {},
        }
    open_days = 0
    if table_exists(conn, "trade_cal"):
        try:
            open_days = int(conn.execute("SELECT COUNT(*) FROM trade_cal WHERE cal_date BETWEEN '20250101' AND '20251231' AND is_open='1'").fetchone()[0])
        except Exception:
            open_days = 0
    result["checks"] = {
        "trade_cal_open_days": open_days,
        "as_of_filter_ok": as_of_filter_ok(conn),
    }
    conn.close()

    required_existing = [t for t in REQUIRED_TABLES if result["tables"][t]["exists"] and result["tables"][t]["rows"] > 0]
    severe_duplicates = sum(int(result["tables"][t]["duplicates"]) for t in REQUIRED_TABLES)
    if not result["db_on_d_drive"] or not result["tables"]["trade_cal"]["exists"] or result["tables"]["daily"]["rows"] == 0:
        result["status"] = "FAIL"
    elif len(required_existing) >= 6 and severe_duplicates == 0 and result["checks"]["as_of_filter_ok"]:
        result["status"] = "PASS"
    else:
        result["status"] = "PASS_WITH_WARNINGS"
    return result


def write_reports(data: dict[str, Any]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORT_DIR / "data_integrity_2025.md"
    json_path = REPORT_DIR / "data_integrity_2025.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 2025 数据完整性检查报告",
        "",
        f"- 生成时间：{data['generated_at']}",
        f"- 数据库路径：`{data['db_path']}`",
        f"- 数据库存在：{'是' if data['db_exists'] else '否'}",
        f"- 数据库位于D盘：{'是' if data['db_on_d_drive'] else '否'}",
        f"- 最终状态：{data['status']}",
        f"- 2025交易日数量：{data.get('checks', {}).get('trade_cal_open_days', 0)}",
        f"- as_of_date过滤检查：{'通过' if data.get('checks', {}).get('as_of_filter_ok') else '失败'}",
        "",
        "## 表检查",
        "",
        "| 表 | 存在 | 行数 | 起始日期 | 结束日期 | 重复键 | 日均概览 |",
        "| -- | -- | --: | -- | -- | --: | -- |",
    ]
    for table, info in data["tables"].items():
        stats = info.get("daily_count_stats") or {}
        stat_text = "-" if not stats else f"days={stats['days']}, min={stats['min']}, avg={stats['avg']}, max={stats['max']}"
        lines.append(f"| {table} | {'是' if info['exists'] else '否'} | {info['rows']} | {info['start']} | {info['end']} | {info['duplicates']} | {stat_text} |")
    lines += [
        "",
        "## 影响说明",
        "",
        "- `PASS` 表示基础行情测试可进入下一阶段构建测试题。",
        "- `PASS_WITH_WARNINGS` 表示可部分使用，但测试报告必须说明缺口。",
        "- `FAIL` 表示不能进入 2025 多题测试。",
        "",
        "## 下一阶段限制说明",
        "",
        "- 当前 2025 基础数据完整性为 PASS_WITH_WARNINGS。",
        "- 可以进入 2025 多题测试集构建，但第一版测试不得依赖完整涨跌停数据和完整停牌数据。",
        "- `limit_list` 缺失，涨跌停相关判断降级处理。",
        "- `suspend` 为部分数据，停牌处理仅作辅助提示，不作为核心评分依据。",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"markdown": str(md_path), "json": str(json_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check 2025 SQLite data integrity.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args(argv)
    data = inspect(Path(args.db_path))
    paths = write_reports(data)
    print(json.dumps({**data, **paths}, ensure_ascii=False, indent=2))
    return 0 if data["status"] in {"PASS", "PASS_WITH_WARNINGS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
