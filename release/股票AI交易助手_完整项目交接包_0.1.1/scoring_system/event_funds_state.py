from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
from scoring_system.project_paths import database_path


ROOT = Path(__file__).resolve().parents[1]
SQLITE_PATH = database_path(ROOT)
SCORES_DIR = ROOT / "data" / "processed" / "scores"
REPORT_DIR = ROOT / "reports" / "enhanced"


EVENT_KEYWORDS = {
    "政策": ["政策", "发改委", "工信部", "国务院", "财政部", "商务部", "监管", "审批", "支持", "鼓励"],
    "公告": ["公告", "业绩预告", "业绩快报", "减持", "增持", "回购", "解禁", "问询", "立案", "处罚"],
    "业绩": ["业绩", "利润", "营收", "净利", "预告", "快报", "亏损", "扭亏", "增长"],
    "新闻": ["新闻", "突发", "澄清", "传闻", "媒体", "合作", "中标", "订单"],
}


def latest_date() -> str:
    dates: list[str] = []
    for path in SCORES_DIR.glob("sector_scores_*_calibrated.csv"):
        dates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    if not dates:
        raise FileNotFoundError("no score dates")
    return sorted(set(dates))[-1]


def recent_dates(limit: int = 2) -> list[str]:
    dates: list[str] = []
    with conn() as c:
        try:
            rows = c.execute(
                "SELECT DISTINCT trade_date FROM daily ORDER BY trade_date DESC LIMIT ?",
                (limit,),
            ).fetchall()
            dates = [str(r[0]) for r in rows if r and r[0]]
        except Exception:
            pass
    if len(dates) >= limit:
        return dates[::-1]
    return []


def conn() -> sqlite3.Connection:
    return sqlite3.connect(SQLITE_PATH)


def read_daily_window(as_of: str, days: int = 5) -> pd.DataFrame:
    with conn() as c:
        date_rows = c.execute(
            "SELECT DISTINCT trade_date FROM daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT ?",
            (as_of, days),
        ).fetchall()
        dates = [str(r[0]) for r in date_rows if r and r[0]]
        if not dates:
            return pd.DataFrame()
        marks = ",".join("?" for _ in dates)
        return pd.read_sql_query(
            f"""
            SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, d.pre_close, d.pct_chg,
                   d.vol, d.amount, d.amount_yuan, d.return,
                   b.turnover_rate, b.volume_ratio, b.total_mv_yuan, b.circ_mv_yuan
            FROM daily d
            LEFT JOIN daily_basic b
              ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
            WHERE d.trade_date IN ({marks})
            ORDER BY d.ts_code, d.trade_date
            """,
            c,
            params=dates,
        )


def market_proxy(day_df: pd.DataFrame, prev_df: pd.DataFrame | None = None) -> dict[str, Any]:
    if day_df.empty:
        return {}
    today = day_df.copy()
    prev = prev_df.copy() if prev_df is not None and not prev_df.empty else pd.DataFrame()
    today_amount = float(today["amount_yuan"].sum())
    prev_amount = float(prev["amount_yuan"].sum()) if not prev.empty else None
    down = today[today["pct_chg"] < 0]
    up = today[today["pct_chg"] > 0]
    return {
        "market_amount_today_yuan": today_amount,
        "market_amount_prev_yuan": prev_amount,
        "amount_change_ratio": (today_amount / prev_amount - 1) if prev_amount else None,
        "up_count": int(len(up)),
        "down_count": int(len(down)),
        "up_ratio": float(len(up) / len(today)) if len(today) else None,
        "avg_turnover_rate": float(today["turnover_rate"].fillna(0).mean()) if "turnover_rate" in today else None,
        "volume_ratio_avg": float(today["volume_ratio"].fillna(0).mean()) if "volume_ratio" in today else None,
        "large_down_count": int((today["pct_chg"] <= -5).sum()),
        "large_up_count": int((today["pct_chg"] >= 5).sum()),
    }


def sector_proxy(as_of: str) -> pd.DataFrame:
    path = SCORES_DIR / f"sector_scores_{as_of}_calibrated.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"index_code": "string"})
    cols = [c for c in ["index_code", "industry_name", "score", "grade", "amount_share", "amount_share_5d_avg", "amount_share_change_ratio", "quote_coverage", "weighted_mv_coverage", "risk_tips", "data_quality"] if c in df.columns]
    return df[cols].copy()


def event_flags(text: str) -> list[str]:
    found: list[str] = []
    for cat, kws in EVENT_KEYWORDS.items():
        if any(k in text for k in kws):
            found.append(cat)
    return found


def classify_shock(prev: dict[str, Any], curr: dict[str, Any]) -> str:
    score_drop = float(curr.get("score", 0)) - float(prev.get("score", 0))
    grade = str(curr.get("grade", ""))
    amount_ratio = float(curr.get("amount_share_change_ratio") or 0)
    if grade.startswith("E") and score_drop <= -20 and amount_ratio < -0.15:
        return "崩塌"
    if grade.startswith("E") or score_drop <= -15:
        return "退潮"
    if score_drop <= -8:
        return "正常分歧"
    return "延续/观察"


def build_report(as_of: str) -> dict[str, Any]:
    sec = sector_proxy(as_of)
    window_dates = recent_dates(limit=2)
    today_df = read_daily_window(as_of, days=1)
    prev_df = read_daily_window(window_dates[0], days=1) if window_dates and window_dates[0] != as_of else pd.DataFrame()
    market = market_proxy(today_df, prev_df)
    rows: list[dict[str, Any]] = []
    if not sec.empty:
        prev_dates = [d for d in window_dates if d != as_of]
        prev_path = SCORES_DIR / f"sector_scores_{prev_dates[-1]}_calibrated.csv" if prev_dates else None
        prev = pd.read_csv(prev_path, dtype={"index_code": "string"}) if prev_path and prev_path.exists() else pd.DataFrame()
        prev_map = prev.set_index("index_code").to_dict("index") if not prev.empty else {}
        for _, r in sec.iterrows():
            code = str(r.get("index_code"))
            p = prev_map.get(code, {})
            rows.append(
                {
                    "index_code": code,
                    "industry_name": r.get("industry_name"),
                    "score": float(r.get("score", 0)),
                    "grade": r.get("grade"),
                    "amount_share": r.get("amount_share"),
                    "amount_share_change_ratio": r.get("amount_share_change_ratio"),
                    "quote_coverage": r.get("quote_coverage"),
                    "shock_state": classify_shock(p, r) if p else "延续/观察",
                    "event_risk_tips": ", ".join(event_flags(str(r.get("risk_tips", "")))) or "未识别",
                    "event_layer_note": "政策/公告/业绩/新闻未结构化，当前仅保留代理标记",
                }
            )
    return {"as_of_date": as_of, "market_proxy": market, "sector_events": rows}


def write_outputs(payload: dict[str, Any]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    as_of = payload["as_of_date"]
    json_path = REPORT_DIR / f"event_funds_state_{as_of}.json"
    md_path = REPORT_DIR / f"event_funds_state_{as_of}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    market = payload.get("market_proxy", {})
    rows = payload.get("sector_events", [])
    lines = [
        f"# 事件面与资金代理状态 {as_of}",
        "",
        "## 市场代理",
        f"- 今日成交额：{market.get('market_amount_today_yuan', '-')}",
        f"- 较前一日成交额变化：{market.get('amount_change_ratio', '-')}",
        f"- 上涨家数：{market.get('up_count', '-')}",
        f"- 下跌家数：{market.get('down_count', '-')}",
        f"- 上涨占比：{market.get('up_ratio', '-')}",
        f"- 放量下跌数：{market.get('large_down_count', '-')}",
        "",
        "## 板块事件代理",
    ]
    for r in rows[:20]:
        lines.extend(
            [
                f"- {r['industry_name']} {r['index_code']}：{r['shock_state']}，成交占比变化 {r.get('amount_share_change_ratio', '-')}, 风险提示 {r['event_risk_tips']}",
            ]
        )
    lines.extend(["", "## 说明", "- 事件面暂未接入公告/新闻原文结构化，只保留可核验代理层。"])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build event/funds/state enhancement report")
    parser.add_argument("--as-of", default="", dest="as_of")
    args = parser.parse_args(argv)
    as_of = args.as_of or latest_date()
    payload = build_report(as_of)
    paths = write_outputs(payload)
    print(json.dumps({"as_of_date": as_of, **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
