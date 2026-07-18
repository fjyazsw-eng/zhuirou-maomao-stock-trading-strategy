from __future__ import annotations

import sqlite3
from typing import Any

import pandas as pd


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def table_stats(conn: sqlite3.Connection, table: str, date_col: str | None = "trade_date") -> dict[str, Any]:
    if not table_exists(conn, table):
        return {"exists": False, "rows": 0, "min_date": None, "max_date": None, "trade_days": 0}
    rows = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    stats = {"exists": True, "rows": rows, "min_date": None, "max_date": None, "trade_days": None}
    if date_col:
        cols = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if date_col in cols:
            min_date, max_date, days = conn.execute(
                f'SELECT MIN("{date_col}"), MAX("{date_col}"), COUNT(DISTINCT "{date_col}") FROM "{table}"'
            ).fetchone()
            stats.update({"min_date": min_date, "max_date": max_date, "trade_days": int(days or 0)})
    return stats


def safe_merge_table(
    conn: sqlite3.Connection,
    table: str,
    new_df: pd.DataFrame,
    key_cols: list[str],
    date_col: str | None = "trade_date",
) -> dict[str, Any]:
    before = table_stats(conn, table, date_col)
    if new_df is None or new_df.empty:
        return {"table": table, "before": before, "after": before, "incoming_rows": 0, "merged_rows": before["rows"]}

    incoming = new_df.copy()
    for col in key_cols:
        if col not in incoming.columns:
            raise ValueError(f"{table}: missing key column {col}")
        incoming[col] = incoming[col].astype("string")

    if table_exists(conn, table):
        existing = pd.read_sql_query(f'SELECT * FROM "{table}"', conn)
        for col in key_cols:
            if col in existing.columns:
                existing[col] = existing[col].astype("string")
        merged = pd.concat([existing, incoming], ignore_index=True, sort=False)
    else:
        merged = incoming

    merged = merged.drop_duplicates(subset=key_cols, keep="last")
    merged.to_sql(table, conn, if_exists="replace", index=False)
    after = table_stats(conn, table, date_col)
    return {
        "table": table,
        "before": before,
        "after": after,
        "incoming_rows": int(len(incoming)),
        "merged_rows": int(len(merged)),
    }


def create_standard_indexes(conn: sqlite3.Connection) -> None:
    index_sql = [
        "CREATE INDEX IF NOT EXISTS idx_daily_code_date ON daily(ts_code, trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_daily_basic_code_date ON daily_basic(ts_code, trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_index_daily_code_date ON index_daily(ts_code, trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_adj_factor_code_date ON adj_factor(ts_code, trade_date)",
        "CREATE INDEX IF NOT EXISTS idx_index_member_key ON index_member(index_code, con_code, in_date)",
    ]
    for sql in index_sql:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass


def null_report(df: pd.DataFrame, fields: list[str]) -> dict[str, dict[str, float | int]]:
    total = int(len(df))
    report: dict[str, dict[str, float | int]] = {}
    for field in fields:
        if field not in df.columns:
            count = total
        else:
            s = df[field]
            count = int(s.isna().sum() + (s.astype("string").fillna("").str.strip() == "").sum())
            count = min(count, total)
        report[field] = {"null_count": count, "null_ratio": round(count / total, 6) if total else 0.0}
    return report
