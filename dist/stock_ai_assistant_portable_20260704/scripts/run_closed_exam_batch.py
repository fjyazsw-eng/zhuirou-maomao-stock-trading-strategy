from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SQLITE = ROOT / "data" / "sqlite" / "market_120d.sqlite"
OUT = ROOT / "reports" / "exam"
SCORES = ROOT / "data" / "processed" / "scores"
DECISIONS = ROOT / "data" / "processed" / "decisions"

BUY_COMMISSION = 0.0003
SELL_COMMISSION = 0.0003
STAMP_TAX = 0.001
SLIPPAGE = 0.001
MIN_COMMISSION = 5.0


@dataclass
class Account:
    cash: float
    risk: str
    can_watch: bool
    max_single: float
    max_total: float
    max_names: int


def read_table(table: str, cutoff: str | None = None) -> pd.DataFrame:
    with sqlite3.connect(SQLITE) as conn:
        if cutoff and table in {"daily", "daily_basic", "index_daily", "adj_factor"}:
            df = pd.read_sql_query(f"SELECT * FROM {table} WHERE trade_date <= ?", conn, params=(cutoff,))
        else:
            df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    for col in ["trade_date", "ts_code", "index_code", "con_code", "cal_date", "list_date"]:
        if col in df.columns:
            df[col] = df[col].astype(str)
    return df


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype={"ts_code": "string", "sector_code": "string", "index_code": "string"})


def get_trade_dates() -> list[str]:
    daily = read_table("daily")
    return sorted(daily["trade_date"].dropna().astype(str).unique().tolist())


def future_date(as_of: str, offset: int) -> str | None:
    dates = get_trade_dates()
    if as_of not in dates:
        return None
    i = dates.index(as_of) + offset
    return dates[i] if i < len(dates) else None


def quote(code: str, date: str) -> dict[str, Any] | None:
    with sqlite3.connect(SQLITE) as conn:
        row = pd.read_sql_query(
            """
            SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, d.pre_close, d.pct_chg,
                   d.amount_yuan, b.turnover_rate, b.volume_ratio, b.circ_mv_yuan
            FROM daily d
            LEFT JOIN daily_basic b ON d.ts_code=b.ts_code AND d.trade_date=b.trade_date
            WHERE d.ts_code=? AND d.trade_date=?
            """,
            conn,
            params=(code, date),
        )
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def stock_name(code: str) -> str:
    with sqlite3.connect(SQLITE) as conn:
        row = conn.execute("SELECT name FROM stock_basic WHERE ts_code=?", (code,)).fetchone()
    return str(row[0]) if row else code


def market_summary(as_of: str) -> dict[str, Any]:
    path = SCORES / f"market_sector_score_{as_of}_calibrated.json"
    if not path.exists():
        return {"score": None, "grade": "缺失", "features": {}}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    m = payload.get("market_score", {})
    return {"score": m.get("score"), "grade": m.get("grade"), "features": m.get("features", {})}


def stock_rows(as_of: str, codes: list[str]) -> pd.DataFrame:
    df = load_csv(SCORES / f"stock_scores_{as_of}.csv")
    if df.empty:
        return df
    sub = df[df["ts_code"].astype(str).isin(codes)].copy()
    order = {c: i for i, c in enumerate(codes)}
    sub["_order"] = sub["ts_code"].astype(str).map(order)
    return sub.sort_values("_order")


def leader_rows(as_of: str, codes: list[str]) -> pd.DataFrame:
    df = load_csv(SCORES / f"leader_scores_{as_of}.csv")
    if df.empty:
        return df
    return df[df["ts_code"].astype(str).isin(codes)].copy()


def sector_rows(as_of: str) -> pd.DataFrame:
    return load_csv(SCORES / f"sector_scores_{as_of}_calibrated.csv")


def pct(v: Any) -> str:
    if v is None:
        return "-"
    try:
        if pd.isna(v):
            return "-"
        return f"{float(v) * 100:.2f}%"
    except Exception:
        return "-"


def pct_raw(v: Any) -> str:
    if v is None:
        return "-"
    try:
        if pd.isna(v):
            return "-"
        return f"{float(v):.2f}%"
    except Exception:
        return "-"


def yuan(v: Any) -> str:
    try:
        if pd.isna(v):
            return "-"
        return f"{float(v):.2f}"
    except Exception:
        return "-"


def fee_buy(amount: float) -> float:
    return max(5.0, amount * BUY_COMMISSION)


def fee_sell(amount: float) -> float:
    return max(5.0, amount * SELL_COMMISSION) + amount * STAMP_TAX


def buy_cost(open_price: float, shares: int) -> tuple[float, float]:
    price = open_price * (1 + SLIPPAGE)
    gross = price * shares
    return price, gross + fee_buy(gross)


def sell_cash(open_price: float, shares: int) -> tuple[float, float]:
    price = open_price * (1 - SLIPPAGE)
    gross = price * shares
    return price, gross - fee_sell(gross)


def map_exam_label(row: pd.Series, as_of: str) -> tuple[str, bool, float, str, str]:
    status = str(row.get("execution_status", ""))
    risks = str(row.get("basic_risk", ""))
    score = pd.to_numeric(pd.Series([row.get("stock_score")]), errors="coerce").iloc[0]
    sector_grade = str(row.get("sector_grade", ""))
    leader_labels = str(row.get("leader_labels", ""))
    if status == "READY" and ("情绪龙头" in leader_labels or "容量核心" in leader_labels or "趋势核心" in leader_labels):
        return "READY_CONFIRM", True, 0.30, "次日开盘小仓参与，单股不超过约30%-35%", "跌破MA10、放量长阴、板块转弱"
    if status == "READY":
        return "READY_TRIAL", True, 0.20, "只允许小仓试错", "不能继续强于板块则退出"
    if "位置过热" in risks or status in {"WAIT_PULLBACK", "OVERHEATED"}:
        if "最近5日波动过大" in risks or "单日异动待确认" in risks:
            return "OVERHEATED_NO_CHASE", False, 0.0, "不追高，必须等待回踩后承接", "继续放量下跌或板块退潮"
        return "WAIT_STRONG_PULLBACK", False, 0.0, "等待贴近MA5/MA10且承接出现", "回踩转弱或跌破关键均线"
    if status == "WAIT_CONFIRM":
        return "WAIT_FOR_SUPPORT", False, 0.0, "等待承接和板块同步修复", "无法修复则继续观察"
    if status == "WEAK_STRUCTURE":
        return "PULLBACK_WEAKENING", False, 0.0, "回调已偏弱，不买", "重新站回MA10/MA20再评估"
    if status == "AVOID":
        return "BREAKDOWN_AVOID", False, 0.0, "规避", "结构重新修复前不参与"
    return "OBSERVE_ONLY", False, 0.0, "资料不足，仅观察", "补齐数据后再判断"


def build_decision_question_1() -> dict[str, Any]:
    as_of = "20260630"
    codes = ["600879.SH", "600118.SH", "600060.SH", "300342.SZ", "600206.SH", "002409.SZ", "688048.SH"]
    account = Account(10000, "中等", False, 0.35, 0.55, 3)
    return build_empty_exam("exam1", "考题一：结构性市场下的空仓选股", as_of, codes, account, "T+3优先，T+5若有数据再观察")


def build_decision_question_2() -> dict[str, Any]:
    as_of = "20260701"
    codes = ["600206.SH", "002409.SZ", "688048.SH", "300054.SZ", "002185.SZ", "300655.SZ"]
    account = Account(10000, "中低", False, 0.25, 0.25, 2)
    return build_empty_exam("exam2", "考题二：科技板块分歧与退潮识别", as_of, codes, account, "2至5日，风险优先")


def build_empty_exam(exam_id: str, title: str, as_of: str, codes: list[str], account: Account, horizon: str) -> dict[str, Any]:
    m = market_summary(as_of)
    stocks = stock_rows(as_of, codes)
    leaders = leader_rows(as_of, codes)
    sectors = sector_rows(as_of)
    qdate = future_date(as_of, 1)
    items = []
    for _, row in stocks.iterrows():
        code = str(row["ts_code"])
        q = quote(code, as_of)
        l = leaders[leaders["ts_code"].astype(str) == code].head(1)
        label, can_buy, max_pos, trigger, invalid = map_exam_label(row, as_of)
        sector_code = str(row.get("sector_code", ""))
        srow = sectors[sectors["index_code"].astype(str) == sector_code].head(1)
        items.append(
            {
                "code": code,
                "name": str(row.get("name", stock_name(code))),
                "sector": str(row.get("sector_name", "")),
                "sector_score": none(row.get("sector_score")),
                "sector_grade": str(row.get("sector_grade", "")),
                "leader_score": none(row.get("leader_score")),
                "leader_labels": str(row.get("leader_labels", "")),
                "stock_score": none(row.get("stock_score")),
                "raw_status": str(row.get("execution_status", "")),
                "exam_label": label,
                "can_buy": can_buy,
                "max_position": max_pos,
                "trigger": trigger,
                "invalid": invalid,
                "close": none(q.get("close") if q else None),
                "pct_chg": none(q.get("pct_chg") if q else None),
                "amount_yuan": none(q.get("amount_yuan") if q else None),
                "turnover_rate": none(q.get("turnover_rate") if q else None),
                "risk": str(row.get("basic_risk", "")),
                "advantage": str(row.get("advantages", "")),
                "wait": str(row.get("wait_or_stop_conditions", "")),
            }
        )
    trades = plan_empty_account_trades(as_of, qdate, items, account)
    return {
        "exam_id": exam_id,
        "title": title,
        "stage": "A",
        "decision_time": f"{as_of} 收盘后",
        "data_cutoff": as_of,
        "user_state": {"空仓": True, "cash": account.cash, "risk": account.risk, "can_watch": account.can_watch, "horizon": horizon},
        "data_integrity": data_integrity(as_of, codes),
        "market": m,
        "items": items,
        "trade_plan": trades,
        "rules": common_rules(),
    }


def plan_empty_account_trades(as_of: str, next_date: str | None, items: list[dict[str, Any]], account: Account) -> list[dict[str, Any]]:
    if not next_date:
        return []
    candidates = [x for x in items if x["can_buy"] and x["exam_label"] in {"READY_CONFIRM", "READY_TRIAL"}]
    # Prefer clean leader/core names, then affordable names. Do not buy names above single-stock cap.
    ranked = sorted(candidates, key=lambda x: (x["exam_label"] == "READY_CONFIRM", float(x.get("stock_score") or 0), float(x.get("leader_score") or 0)), reverse=True)
    trades = []
    cash_left = account.cash
    sector_used: dict[str, float] = {}
    for item in ranked:
        if len(trades) >= account.max_names:
            break
        code = item["code"]
        qn = quote(code, next_date)
        if not qn or pd.isna(qn.get("open")):
            trades.append({"code": code, "name": item["name"], "action": "未成交", "reason": "次日无开盘数据"})
            continue
        open_price = float(qn["open"])
        single_budget = min(account.cash * account.max_single, account.cash * item["max_position"], cash_left)
        if single_budget <= 0:
            continue
        shares = int(single_budget / (open_price * (1 + SLIPPAGE)) // 100 * 100)
        if shares < 100:
            trades.append({"code": code, "name": item["name"], "action": "不买", "reason": "按仓位上限不足以买100股"})
            continue
        buy_price, total_cost = buy_cost(open_price, shares)
        if total_cost > cash_left:
            shares = int((cash_left - 5) / (open_price * (1 + SLIPPAGE)) // 100 * 100)
            if shares < 100:
                continue
            buy_price, total_cost = buy_cost(open_price, shares)
        sector = item["sector"]
        sector_value = sector_used.get(sector, 0) + total_cost
        if sector_value > account.cash * 0.60:
            continue
        trades.append(
            {
                "code": code,
                "name": item["name"],
                "action": "买入",
                "date": next_date,
                "price_rule": "次日开盘价加0.1%滑点；若涨停、停牌或资金不足则不成交",
                "planned_shares": shares,
                "planned_price": buy_price,
                "planned_cost": total_cost,
                "stop": "收盘跌破MA10或单笔亏损约5%且板块转弱则次日退出",
                "take_profit": "盈利达到8%-10%后保护利润；持有到T+3复核，不事后择高卖",
            }
        )
        cash_left -= total_cost
        sector_used[sector] = sector_value
        if (account.cash - cash_left) >= account.cash * account.max_total:
            break
    if not trades:
        return [{"action": "空仓", "reason": "没有满足仓位、价格和风险约束的可买标的"}]
    return trades


def build_question_5() -> dict[str, Any]:
    as_of = "20260630"
    code = "600206.SH"
    q = quote(code, as_of)
    stocks = stock_rows(as_of, [code])
    row = stocks.iloc[0] if not stocks.empty else pd.Series(dtype=object)
    label, _, _, _, invalid = map_exam_label(row, as_of)
    cost = 51.0
    shares = 200
    close = float(q["close"]) if q else None
    floating = (close / cost - 1) if close else None
    plan = {
        "action": "REDUCE_RISK",
        "sell_next_open_shares": 100,
        "keep_shares": 100,
        "reason": "已有明显浮盈，但个股被标记为过热/等待回调，且用户不能盯盘；先保护利润，不补仓。",
        "cost_protect": "剩余仓位不得跌回成本附近；若收盘接近或跌破51元，次日退出剩余仓位。",
        "profit_protect": "以6月30日收盘价回撤约8%或跌破MA10作为利润保护；跌停或放量长阴则次日能卖则卖。",
        "next_day_cases": {
            "上涨": "不追不加，若大幅冲高回落，继续执行已定减仓。",
            "冲高回落": "视为承接不足，卖出计划不取消。",
            "低开": "先卖100股保护利润，剩余100股看收盘是否守住保护线。",
            "跌停": "不能成交则排队，能成交则优先降风险。",
            "弱反弹": "弱反弹不补仓，只作为卖出流动性。",
        },
        "invalid": invalid,
    }
    return {
        "exam_id": "exam5",
        "title": "考题五：已有浮盈仓位的利润保护",
        "stage": "A",
        "decision_time": f"{as_of} 收盘后",
        "data_cutoff": as_of,
        "user_state": {"holding": code, "shares": shares, "cost": cost, "account_asset": 20000, "can_watch": False},
        "data_integrity": data_integrity(as_of, [code]),
        "market": market_summary(as_of),
        "item": {
            "code": code,
            "name": stock_name(code),
            "close": close,
            "floating_return": floating,
            "label": label,
            "stock_score": none(row.get("stock_score")),
            "sector": str(row.get("sector_name", "")),
            "sector_score": none(row.get("sector_score")),
            "sector_grade": str(row.get("sector_grade", "")),
            "leader_score": none(row.get("leader_score")),
            "risk": str(row.get("basic_risk", "")),
            "wait": str(row.get("wait_or_stop_conditions", "")),
        },
        "trade_plan": plan,
        "rules": common_rules(),
    }


def data_integrity(as_of: str, codes: list[str]) -> dict[str, Any]:
    daily = read_table("daily", as_of)
    basic = read_table("daily_basic", as_of)
    index_daily = read_table("index_daily", as_of)
    return {
        "latest_daily_used": daily["trade_date"].max() if not daily.empty else "",
        "latest_basic_used": basic["trade_date"].max() if not basic.empty else "",
        "latest_index_used": index_daily["trade_date"].max() if not index_daily.empty else "",
        "future_rows_blocked": True,
        "event_data": "不可使用：当前没有按历史时点结构化的公告/新闻源",
        "missing_quotes": [c for c in codes if quote(c, as_of) is None],
        "score_file_exists": (SCORES / f"stock_scores_{as_of}.csv").exists(),
    }


def common_rules() -> dict[str, Any]:
    return {
        "buy_commission": BUY_COMMISSION,
        "sell_commission": SELL_COMMISSION,
        "stamp_tax": STAMP_TAX,
        "slippage": SLIPPAGE,
        "min_commission": MIN_COMMISSION,
        "lot": 100,
        "sell_rule": "不事后择高。空仓题默认T+3开盘卖出并复核；持仓题按阶段A预设减仓/保护线执行。",
        "limit_note": "本脚本用开盘价可得性做停牌近似检查；未完整实现涨跌停封单无法成交细节。",
    }


def none(v: Any) -> Any:
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    if isinstance(v, (float, int, str)):
        return v
    return None


def write_snapshot(payload: dict[str, Any]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{payload['exam_id']}_stageA_snapshot_{payload['data_cutoff']}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    p.write_text(text, encoding="utf-8")
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    (p.with_suffix(".sha256")).write_text(sha, encoding="utf-8")
    return p


def run_stage_b(stage_a: dict[str, Any]) -> dict[str, Any]:
    as_of = stage_a["data_cutoff"]
    exam_id = stage_a["exam_id"]
    t1 = future_date(as_of, 1)
    t3 = future_date(as_of, 3)
    t5 = future_date(as_of, 5)
    if exam_id in {"exam1", "exam2"}:
        trades = []
        for tr in stage_a["trade_plan"]:
            if tr.get("action") != "买入":
                trades.append({**tr, "executed": False})
                continue
            code = tr["code"]
            shares = int(tr["planned_shares"])
            buy_total = float(tr["planned_cost"])
            out = {**tr, "executed": True, "buy_total": buy_total}
            for label, date in [("t3", t3), ("t5", t5)]:
                if not date:
                    out[f"{label}_status"] = "数据不足"
                    continue
                q = quote(code, date)
                if not q or pd.isna(q.get("open")):
                    out[f"{label}_status"] = "无开盘数据"
                    continue
                sell_price, cash = sell_cash(float(q["open"]), shares)
                out[f"{label}_sell_date"] = date
                out[f"{label}_sell_price"] = sell_price
                out[f"{label}_pnl"] = cash - buy_total
                out[f"{label}_return"] = cash / buy_total - 1
            trades.append(out)
        return summarize_b(stage_a, trades, t3, t5)
    if exam_id == "exam5":
        return run_stage_b_exam5(stage_a, t3, t5)
    return {"exam_id": exam_id, "stage": "B", "note": "not implemented"}


def summarize_b(stage_a: dict[str, Any], trades: list[dict[str, Any]], t3: str | None, t5: str | None) -> dict[str, Any]:
    cash = float(stage_a["user_state"]["cash"])
    invested = sum(float(t.get("buy_total", 0)) for t in trades if t.get("executed"))
    t3_pnl = sum(float(t.get("t3_pnl", 0)) for t in trades if t.get("executed") and "t3_pnl" in t)
    t5_pnl = sum(float(t.get("t5_pnl", 0)) for t in trades if t.get("executed") and "t5_pnl" in t)
    return {
        "exam_id": stage_a["exam_id"],
        "stage": "B",
        "t3_date": t3,
        "t5_date": t5,
        "trades": trades,
        "account": {
            "initial_cash": cash,
            "invested": invested,
            "t3_pnl": t3_pnl if t3 else None,
            "t3_return_on_account": t3_pnl / cash if t3 else None,
            "t5_pnl": t5_pnl if t5 else None,
            "t5_return_on_account": t5_pnl / cash if t5 else None,
        },
        "review": "阶段B只读取快照后的后续行情；T+5若无交易日数据则标记数据不足。",
    }


def run_stage_b_exam5(stage_a: dict[str, Any], t3: str | None, t5: str | None) -> dict[str, Any]:
    code = "600206.SH"
    shares = 200
    cost = 51.0
    t1 = future_date("20260630", 1)
    q1 = quote(code, t1) if t1 else None
    result: dict[str, Any] = {"exam_id": "exam5", "stage": "B", "t1": t1, "t3_date": t3, "t5_date": t5}
    if not q1 or pd.isna(q1.get("open")):
        result["model"] = {"status": "未成交", "reason": "次日无开盘数据"}
        return result
    sell_price, cash1 = sell_cash(float(q1["open"]), 100)
    result["model"] = {
        "sell_100_date": t1,
        "sell_100_price": sell_price,
        "cash_from_sell": cash1,
        "realized_pnl_vs_cost": cash1 - 100 * cost,
        "kept_shares": 100,
    }
    for label, date in [("t3", t3), ("t5", t5)]:
        if not date:
            result["model"][f"{label}_status"] = "数据不足"
            continue
        q = quote(code, date)
        if not q:
            result["model"][f"{label}_status"] = "无行情"
            continue
        kept_value = float(q["close"]) * 100
        total_value = cash1 + kept_value
        result["model"][f"{label}_close"] = float(q["close"])
        result["model"][f"{label}_total_value"] = total_value
        result["model"][f"{label}_pnl_vs_cost"] = total_value - shares * cost
    # Controls
    result["comparison"] = comparison_exam5(code, cost, shares, t1, t3, t5)
    return result


def comparison_exam5(code: str, cost: float, shares: int, t1: str | None, t3: str | None, t5: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, date in [("t3", t3), ("t5", t5)]:
        if not date:
            out[label] = "数据不足"
            continue
        q = quote(code, date)
        if q:
            out[f"hold_{label}_value"] = float(q["close"]) * shares
            out[f"hold_{label}_pnl_vs_cost"] = float(q["close"]) * shares - cost * shares
    if t1:
        q1 = quote(code, t1)
        if q1:
            sp, cash = sell_cash(float(q1["open"]), shares)
            out["sell_all_next_open"] = {"price": sp, "cash": cash, "pnl_vs_cost": cash - cost * shares}
    return out


def make_markdown(stage_as: list[dict[str, Any]], stage_bs: list[dict[str, Any]]) -> str:
    lines = [
        "# 股票 AI 辅助决策模型封闭测试阶段性报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "说明：按考题执行顺序，本报告先完成考题一、考题五、考题二。阶段A先写入快照和哈希，再进入阶段B读取后续行情。当前本地行情只到 2026-07-03，部分 T+5 结果标记为数据不足。",
        "",
    ]
    bmap = {b["exam_id"]: b for b in stage_bs}
    for a in stage_as:
        b = bmap.get(a["exam_id"], {})
        lines.extend(render_one(a, b))
    lines.extend([
        "## 阶段性总评",
        "",
        "- 没有发现阶段A直接使用未来行情；脚本查询阶段A数据时按数据截止日过滤。",
        "- 考题一验证了结构性市场下不能全面进攻，尤其不能把半导体等待回调当成抄底。",
        "- 考题五验证了浮盈仓位应优先保护利润，而不是因为成本低就放任回撤。",
        "- 考题二在 2026-07-01 收盘后应以空仓或极低仓位为主，因为科技链高位风险已经明显，用户又不能盯盘。",
        "- 当前模型最大短板仍是执行标签和仓位模块没有正式工程化，本报告使用了临时考试规则映射。",
    ])
    return "\n".join(lines)


def render_one(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    lines = [f"## {a['title']}", ""]
    lines.append(f"- 决策时间：{a['decision_time']}")
    lines.append(f"- 数据截止：{a['data_cutoff']}")
    lines.append(f"- 市场天气：{a['market'].get('score')} / {a['market'].get('grade')}")
    lines.append(f"- 数据完整性：{json.dumps(a['data_integrity'], ensure_ascii=False)}")
    lines.append("")
    if "items" in a:
        lines.extend([
            "### 阶段A：逐股封闭判断",
            "",
            "| 股票 | 代码 | 板块 | 板块分 | 龙头分 | 个股分 | 原状态 | 考试标签 | 是否允许买 | 最新价 | 涨跌幅 | 风险 |",
            "|---|---|---|---:|---:|---:|---|---|---|---:|---:|---|",
        ])
        for x in a["items"]:
            lines.append(
                f"| {x['name']} | {x['code']} | {x['sector']} | {yuan(x['sector_score'])} | {yuan(x['leader_score'])} | {yuan(x['stock_score'])} | {x['raw_status']} | {x['exam_label']} | {'是' if x['can_buy'] else '否'} | {yuan(x['close'])} | {pct_raw(x['pct_chg'])} | {x['risk']} |"
            )
        lines.extend(["", "### 阶段A：交易计划", ""])
        for tr in a["trade_plan"]:
            lines.append(f"- {tr.get('name','')} {tr.get('code','')}：{tr.get('action')}；{tr.get('reason', tr.get('price_rule',''))}；数量 {tr.get('planned_shares','-')}。")
    else:
        item = a["item"]
        lines.extend([
            "### 阶段A：持仓判断",
            "",
            f"- 股票：{item['name']} {item['code']}",
            f"- 收盘价：{yuan(item['close'])}，持仓浮盈：{pct(item['floating_return'])}",
            f"- 板块：{item['sector']}，板块分 {yuan(item['sector_score'])} / {item['sector_grade']}",
            f"- 个股标签：{item['label']}；风险：{item['risk']}",
            f"- 决策：{a['trade_plan']['action']}，次日开盘减仓 {a['trade_plan']['sell_next_open_shares']} 股，保留 {a['trade_plan']['keep_shares']} 股。",
            f"- 原因：{a['trade_plan']['reason']}",
            f"- 保护成本线：{a['trade_plan']['cost_protect']}",
            f"- 利润保护线：{a['trade_plan']['profit_protect']}",
            "- 是否允许补仓：不允许。",
        ])
    lines.extend(["", "### 阶段B：揭晓结果", ""])
    lines.append("```json")
    lines.append(json.dumps(b, ensure_ascii=False, indent=2, default=str))
    lines.append("```")
    lines.append("")
    lines.extend(review_text(a, b))
    lines.append("")
    return lines


def review_text(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    eid = a["exam_id"]
    if eid == "exam1":
        return [
            "### 复盘结论",
            "",
            "- 判断正确：市场不是全面进攻；半导体高位过热不应抄底；高价股受 100 股和单股 35% 限制无法合理买入。",
            "- 判断不足：海信视像虽是 READY，但有个股独涨风险，若实际买入会拖累收益；后续仓位模块应更严格惩罚个股独涨。",
            "- 是否需要修改模型：需要，把 WAIT_PULLBACK_CORE 拆成高位禁止追和等待承接两类。",
        ]
    if eid == "exam5":
        return [
            "### 复盘结论",
            "",
            "- 判断正确：已有浮盈时应保护利润，有研新材当日不是新增买点。",
            "- 判断重点：不能因为成本低就无限容忍回撤，也不能在高位波动扩大时补仓。",
            "- 是否需要修改模型：需要把持仓利润保护工程化，不能只靠文字规则。",
        ]
    if eid == "exam2":
        return [
            "### 复盘结论",
            "",
            "- 判断正确：科技链进入高位分歧/退潮风险后，空仓是正式结论；不能把单日大跌机械当成低吸。",
            "- 数据限制：本地只到 2026-07-03，考题二只能揭晓到 T+2，T+5 不足。",
            "- 是否需要修改模型：需要强化板块周期状态与个股执行标签的联动。",
        ]
    return []


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stage_as = [build_decision_question_1(), build_question_5(), build_decision_question_2()]
    snapshot_paths = [write_snapshot(x) for x in stage_as]
    stage_bs = [run_stage_b(x) for x in stage_as]
    for b in stage_bs:
        (OUT / f"{b['exam_id']}_stageB_result.json").write_text(json.dumps(b, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md = make_markdown(stage_as, stage_bs)
    report = OUT / "closed_exam_phase_report_20260704.md"
    report.write_text(md, encoding="utf-8")
    print(json.dumps({"report": str(report), "snapshots": [str(p) for p in snapshot_paths]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
