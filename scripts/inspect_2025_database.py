from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("D:/股票AI交易助手数据/sqlite/market_2025.sqlite")


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    return [str(x[0]) for x in rows]


def table_info(conn: sqlite3.Connection, table: str) -> dict[str, object]:
    rows = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    date_col = "cal_date" if table == "trade_cal" else "trade_date"
    start = end = ""
    try:
        row = conn.execute(f"SELECT MIN({date_col}), MAX({date_col}) FROM {table}").fetchone()
        start, end = str(row[0] or ""), str(row[1] or "")
    except Exception:
        pass
    return {"rows": rows, "start": start, "end": end}


def inspect(db_path: Path) -> dict[str, object]:
    data: dict[str, object] = {
        "db_path": str(db_path),
        "exists": db_path.exists(),
        "on_d_drive": db_path.exists() and db_path.resolve().drive.upper().startswith("D:"),
        "tables": {},
        "missing_required": [],
    }
    required = ["trade_cal", "stock_basic", "daily", "daily_basic", "adj_factor", "index_daily", "limit_list", "suspend"]
    if not db_path.exists():
        data["missing_required"] = required
        return data
    conn = sqlite3.connect(db_path)
    names = table_names(conn)
    data["table_names"] = names
    data["missing_required"] = [x for x in required if x not in names]
    data["tables"] = {name: table_info(conn, name) for name in names}
    if "fetch_log" in names:
        rows = conn.execute("SELECT table_name,status,row_count,created_at,error_message FROM fetch_log ORDER BY id DESC LIMIT 20").fetchall()
        data["latest_fetch_log"] = [
            {"table": r[0], "status": r[1], "rows": r[2], "created_at": r[3], "error": r[4]} for r in rows
        ]
    conn.close()
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect 2025 SQLite database.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    args = parser.parse_args(argv)
    print(json.dumps(inspect(Path(args.db_path)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
