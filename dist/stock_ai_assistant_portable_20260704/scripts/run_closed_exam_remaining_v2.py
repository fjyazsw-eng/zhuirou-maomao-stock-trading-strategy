from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.leader_score import run_leader_score
from scoring_system.mvp_score import run_score
from scoring_system.stock_score import run_stock_score

SQLITE = ROOT / "data" / "sqlite" / "market_120d.sqlite"
SCORES = ROOT / "data" / "processed" / "scores"
OUT = ROOT / "reports" / "exam_v2"

BUY_COMMISSION = 0.0003
SELL_COMMISSION = 0.0003
STAMP_TAX = 0.001
SLIPPAGE = 0.001
MIN_COMMISSION = 5.0
LOT = 100
SCRIPT_VERSION = "closed-exam-v2-20260704"


@dataclass
class ExamSpec:
    exam_id: str
    title: str
    as_of: str
    cash: float
    risk: str
    can_watch: bool
    holding_days: int
    max_names: int
    max_single: float
    max_total: float
    codes: list[str]
    sectors: list[str]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def read_sql(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    with sqlite3.connect(SQLITE) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def trade_dates() -> list[str]:
    df = read_sql("SELECT DISTINCT trade_date FROM daily ORDER BY trade_date")
    return [str(x) for x in df["trade_date"].tolist()]


def next_trade_date(date: str, offset: int = 1) -> str | None:
    dates = trade_dates()
    if date not in dates:
        return None
    i = dates.index(date) + offset
    return dates[i] if i < len(dates) else None


def date_window(start: str, days: int) -> list[str]:
    dates = trade_dates()
    if start not in dates:
        return []
    i = dates.index(start)
    return dates[i : i + days]


def quote(code: str, date: str) -> dict[str, Any] | None:
    df = read_sql(
        """
        SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, d.pre_close, d.pct_chg,
               d.amount_yuan, d.return, b.turnover_rate, b.volume_ratio, b.circ_mv_yuan
        FROM daily d
        LEFT JOIN daily_basic b ON d.ts_code=b.ts_code AND d.trade_date=b.trade_date
        WHERE d.ts_code=? AND d.trade_date=?
        """,
        (code, date),
    )
    if df.empty:
        return None
    return df.iloc[0].to_dict()


def bars(code: str, end_date: str, lookback: int = 30) -> pd.DataFrame:
    df = read_sql(
        """
        SELECT d.ts_code, d.trade_date, d.open, d.high, d.low, d.close, d.pct_chg, d.amount_yuan,
               b.turnover_rate
        FROM daily d
        LEFT JOIN daily_basic b ON d.ts_code=b.ts_code AND d.trade_date=b.trade_date
        WHERE d.ts_code=? AND d.trade_date<=?
        ORDER BY d.trade_date DESC
        LIMIT ?
        """,
        (code, end_date, lookback),
    )
    if df.empty:
        return df
    df = df.sort_values("trade_date").reset_index(drop=True)
    for col in ["open", "high", "low", "close", "pct_chg", "amount_yuan", "turnover_rate"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    return df


def stock_name(code: str) -> str:
    df = read_sql("SELECT name FROM stock_basic WHERE ts_code=?", (code,))
    return str(df.iloc[0]["name"]) if not df.empty else code


def latest_score_row(as_of: str, code: str) -> dict[str, Any]:
    path = SCORES / f"stock_scores_{as_of}.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"ts_code": "string"})
    hit = df[df["ts_code"].astype(str) == code]
    return hit.iloc[0].to_dict() if not hit.empty else {}


def market(as_of: str) -> dict[str, Any]:
    path = SCORES / f"market_sector_score_{as_of}_calibrated.json"
    if not path.exists():
        return {"score": None, "grade": "缺失"}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    return payload.get("market_score", {})


def sector_scores(as_of: str) -> pd.DataFrame:
    path = SCORES / f"sector_scores_{as_of}_calibrated.csv"
    return pd.read_csv(path, dtype={"index_code": "string"}) if path.exists() else pd.DataFrame()


def fee_buy(gross: float) -> float:
    return max(MIN_COMMISSION, gross * BUY_COMMISSION)


def fee_sell(gross: float) -> float:
    return max(MIN_COMMISSION, gross * SELL_COMMISSION) + gross * STAMP_TAX


def buy_price(open_price: float) -> float:
    return open_price * (1 + SLIPPAGE)


def sell_price(open_price: float) -> float:
    return open_price * (1 - SLIPPAGE)


def map_label(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("execution_status", ""))
    risk = str(row.get("basic_risk", ""))
    leader_labels = str(row.get("leader_labels", ""))
    if "个股独涨但板块不同步" in risk and status == "READY":
        return {"label": "READY_TRIAL", "can_buy": True, "max_pos": 0.18, "reason": "执行层约束：个股独涨但板块不同步，降为试错"}
    if status == "READY" and any(x in leader_labels for x in ["情绪龙头", "容量核心", "趋势核心"]):
        return {"label": "READY_CONFIRM", "can_buy": True, "max_pos": 0.30, "reason": "核心身份较明确，允许确认参与"}
    if status == "READY":
        return {"label": "READY_TRIAL", "can_buy": True, "max_pos": 0.20, "reason": "非强核心，仅小仓试错"}
    if "位置过热" in risk or status in {"WAIT_PULLBACK", "OVERHEATED"}:
        return {"label": "OVERHEATED_NO_CHASE", "can_buy": False, "max_pos": 0.0, "reason": "过热或等待回踩，不作为买点"}
    if status == "WAIT_CONFIRM":
        return {"label": "WAIT_FOR_SUPPORT", "can_buy": False, "max_pos": 0.0, "reason": "等待承接确认"}
    if status == "WEAK_STRUCTURE":
        return {"label": "PULLBACK_WEAKENING", "can_buy": False, "max_pos": 0.0, "reason": "结构偏弱"}
    if status == "AVOID":
        return {"label": "BREAKDOWN_AVOID", "can_buy": False, "max_pos": 0.0, "reason": "规避"}
    return {"label": "OBSERVE_ONLY", "can_buy": False, "max_pos": 0.0, "reason": "仅观察"}


def prepare_scores(as_of: str, sectors: list[str], codes: list[str]) -> None:
    run_score(as_of)
    run_leader_score(as_of, sectors)
    run_stock_score(as_of, codes, no_api=True)


def audit_payload(as_of: str, codes: list[str]) -> dict[str, Any]:
    tables = {}
    for table in ["daily", "daily_basic", "index_daily"]:
        df = read_sql(f"SELECT MIN(trade_date) min_date, MAX(trade_date) max_date, COUNT(*) rows FROM {table} WHERE trade_date<=?", (as_of,))
        tables[table] = df.iloc[0].to_dict()
    files = [
        SCORES / f"market_sector_score_{as_of}_calibrated.json",
        SCORES / f"sector_scores_{as_of}_calibrated.csv",
        SCORES / f"leader_scores_{as_of}.csv",
        SCORES / f"stock_scores_{as_of}.csv",
        ROOT / "config" / "stock_score.yaml",
        ROOT / "config" / "leader_score.yaml",
        ROOT / "config" / "market_score.yaml",
        ROOT / "config" / "sector_score.yaml",
    ]
    return {
        "source": "本地SQLite和本地模型评分文件；原始数据来自此前Tushare缓存，本阶段未实时调用Tushare",
        "cutoff": as_of,
        "future_rows_blocked": True,
        "tables": tables,
        "codes": codes,
        "files": [{"path": str(p), "exists": p.exists(), "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds") if p.exists() else "", "sha256": sha256_file(p)} for p in files],
        "script": str(Path(__file__).relative_to(ROOT)),
        "script_sha256": sha256_file(Path(__file__)),
        "version": SCRIPT_VERSION,
    }


def make_stage_a(spec: ExamSpec, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    prepare_scores(spec.as_of, spec.sectors, spec.codes)
    m = market(spec.as_of)
    rows = []
    for code in spec.codes:
        row = latest_score_row(spec.as_of, code)
        q = quote(code, spec.as_of)
        label = map_label(row)
        rows.append({
            "code": code,
            "name": str(row.get("name") or stock_name(code)),
            "sector": str(row.get("sector_name", "")),
            "sector_score": row.get("sector_score"),
            "sector_grade": row.get("sector_grade"),
            "leader_score": row.get("leader_score"),
            "leader_labels": row.get("leader_labels"),
            "stock_score": row.get("stock_score"),
            "raw_status": row.get("execution_status"),
            "risk": row.get("basic_risk"),
            "wait": row.get("wait_or_stop_conditions"),
            "close": q.get("close") if q else None,
            "pct_chg": q.get("pct_chg") if q else None,
            **label,
        })
    plan = build_trade_plan(spec, rows)
    payload = {
        "exam_id": spec.exam_id,
        "title": spec.title,
        "stage": "A",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "decision_time": f"{spec.as_of} 收盘后",
        "data_cutoff": spec.as_of,
        "model_versions": {"exam_script": SCRIPT_VERSION, "weights_changed": False},
        "account": {"cash": spec.cash, "risk": spec.risk, "can_watch": spec.can_watch, "max_single": spec.max_single, "max_total": spec.max_total, "max_names": spec.max_names},
        "market": {"score": m.get("score"), "grade": m.get("grade"), "features": m.get("features", {})},
        "items": rows,
        "trade_plan": plan,
        "fixed_rules": {
            "buy": "若允许买入，买入成交日T为决策日后第1个交易日开盘，成交价=开盘价*(1+0.1%滑点)，100股整数倍，资金不足则不成交。",
            "sell": f"若未提前触发退出，则在第{spec.holding_days}个持有交易日开盘卖出，成交价=开盘价*(1-0.1%滑点)。",
            "stop_loss": "收盘亏损达到5%或收盘跌破MA10且个股/板块转弱，次日开盘退出。",
            "take_profit": "盘中最高浮盈达到10%后，如从持仓最高价回撤5%，次日开盘保护性卖出。",
            "profit_protection": "浮盈持仓优先保护利润，不因亏损扩大而补仓。",
        },
        "audit": audit_payload(spec.as_of, spec.codes),
        "extra": extra or {},
    }
    return payload


def build_trade_plan(spec: ExamSpec, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buy_date = next_trade_date(spec.as_of, 1)
    if not buy_date:
        return [{"action": "空仓", "reason": "无下一交易日数据"}]
    candidates = [r for r in rows if r.get("can_buy")]
    candidates = sorted(candidates, key=lambda r: (r["label"] == "READY_CONFIRM", float(r.get("stock_score") or 0), float(r.get("leader_score") or 0)), reverse=True)
    trades = []
    cash_left = spec.cash
    total_budget = spec.cash * spec.max_total
    used = 0.0
    for r in candidates:
        if len([t for t in trades if t.get("action") == "买入"]) >= spec.max_names:
            break
        if used >= total_budget:
            break
        q = quote(r["code"], buy_date)
        if not q or pd.isna(q.get("open")):
            trades.append({"action": "未成交", "code": r["code"], "name": r["name"], "reason": "次日无开盘价，视为停牌或数据缺失"})
            continue
        budget = min(spec.cash * spec.max_single, spec.cash * float(r.get("max_pos") or 0), total_budget - used, cash_left)
        shares = int((budget - MIN_COMMISSION) / buy_price(float(q["open"])) // LOT * LOT)
        if shares < LOT:
            trades.append({"action": "不买", "code": r["code"], "name": r["name"], "reason": "仓位上限或资金不足以买100股"})
            continue
        price = buy_price(float(q["open"]))
        gross = price * shares
        cost = gross + fee_buy(gross)
        if cost > cash_left:
            continue
        trades.append({"action": "买入", "code": r["code"], "name": r["name"], "buy_date": buy_date, "shares": shares, "buy_price": price, "buy_cost": cost, "label": r["label"], "reason": r["reason"]})
        cash_left -= cost
        used += cost
    if not any(t.get("action") == "买入" for t in trades):
        trades.append({"action": "空仓", "reason": "没有满足执行标签、仓位和100股约束的标的"})
    return trades


def write_snapshot(payload: dict[str, Any]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{payload['exam_id']}_stageA_{payload['data_cutoff']}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    path.write_text(text, encoding="utf-8")
    sha = sha256_file(path)
    path.with_suffix(".sha256").write_text(sha, encoding="utf-8")
    return path


def verify_snapshot(path: Path) -> dict[str, Any]:
    expected = path.with_suffix(".sha256").read_text(encoding="utf-8").strip() if path.with_suffix(".sha256").exists() else ""
    actual = sha256_file(path)
    return {"path": str(path), "expected_sha256": expected, "actual_sha256": actual, "ok": bool(expected and expected == actual)}


def simulate_stage_b(snapshot: Path) -> dict[str, Any]:
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    spec_days = int(payload["fixed_rules"]["sell"].split("第")[1].split("个")[0])
    ver = verify_snapshot(snapshot)
    trades = []
    cash = float(payload["account"]["cash"])
    equity_by_day: dict[str, float] = {}
    for trade in payload["trade_plan"]:
        if trade.get("action") != "买入":
            trades.append({**trade, "executed": False, "daily_log": []})
            continue
        code = trade["code"]
        shares = int(trade["shares"])
        buy_date = trade["buy_date"]
        dates = date_window(buy_date, spec_days + 1)
        if len(dates) < spec_days:
            trades.append({**trade, "executed": True, "status": "观察期数据不足", "daily_log": []})
            continue
        entry = float(trade["buy_price"])
        high_since = entry
        exit_info = None
        logs = []
        for i, d in enumerate(dates, start=1):
            q = quote(code, d)
            if not q:
                logs.append({"date": d, "action": "无行情，无法检查"})
                continue
            close = float(q["close"])
            high = float(q["high"])
            low = float(q["low"])
            high_since = max(high_since, high)
            pnl_close = close / entry - 1
            pnl_low = low / entry - 1
            bdf = bars(code, d, 20)
            ma10 = float(bdf.iloc[-1]["ma10"]) if len(bdf) and not pd.isna(bdf.iloc[-1].get("ma10")) else None
            stop_hit = pnl_close <= -0.05 or (ma10 is not None and close < ma10 and pnl_close < 0)
            profit_hit = high_since / entry - 1 >= 0.10 and close / high_since - 1 <= -0.05
            action = "继续持有"
            trigger = ""
            if i >= spec_days:
                sp = sell_price(float(q["open"]))
                gross = sp * shares
                exit_info = {"date": d, "reason": f"第{spec_days}个持有交易日开盘固定卖出", "sell_price": sp, "cash": gross - fee_sell(gross)}
                action = "固定卖出"
            elif stop_hit:
                nd = next_trade_date(d, 1)
                nq = quote(code, nd) if nd else None
                if nq:
                    sp = sell_price(float(nq["open"]))
                    gross = sp * shares
                    exit_info = {"date": nd, "reason": "止损触发后次日开盘卖出", "sell_price": sp, "cash": gross - fee_sell(gross)}
                    action = "触发止损"
                    trigger = "亏损达到5%或跌破MA10"
            elif profit_hit:
                nd = next_trade_date(d, 1)
                nq = quote(code, nd) if nd else None
                if nq:
                    sp = sell_price(float(nq["open"]))
                    gross = sp * shares
                    exit_info = {"date": nd, "reason": "利润保护触发后次日开盘卖出", "sell_price": sp, "cash": gross - fee_sell(gross)}
                    action = "触发利润保护"
                    trigger = "浮盈后回撤"
            logs.append({"date": d, "H": i, "open": q["open"], "high": high, "low": low, "close": close, "floating_return_close": pnl_close, "floating_return_low": pnl_low, "ma10": ma10, "stop": stop_hit, "profit_protection": profit_hit, "trigger": trigger, "action": action})
            if exit_info:
                break
        if not exit_info:
            trades.append({**trade, "executed": True, "status": "观察期数据不足或未退出", "daily_log": logs})
            continue
        pnl = exit_info["cash"] - float(trade["buy_cost"])
        max_float_loss = min([x.get("floating_return_low", 0) for x in logs] or [0])
        max_float_gain = max([x.get("floating_return_close", 0) for x in logs] or [0])
        trades.append({**trade, "executed": True, "exit": exit_info, "pnl": pnl, "return": pnl / float(trade["buy_cost"]), "max_float_loss": max_float_loss, "max_float_gain": max_float_gain, "daily_log": logs})
    total_pnl = sum(float(t.get("pnl", 0)) for t in trades)
    invested = sum(float(t.get("buy_cost", 0)) for t in trades if t.get("executed"))
    return {"exam_id": payload["exam_id"], "stage": "B", "snapshot_check": ver, "trades": trades, "account": {"initial_cash": cash, "invested": invested, "capital_usage": invested / cash if cash else 0, "total_pnl": total_pnl, "return_on_account": total_pnl / cash if cash else 0, "max_drawdown_proxy": min([float(t.get("max_float_loss", 0)) for t in trades] or [0])}, "generated_at": datetime.now().isoformat(timespec="seconds")}


def exam3() -> ExamSpec:
    return ExamSpec("exam3", "考题三：强势阶段中的入场选择", "20260616", 20000, "中等", False, 5, 2, 0.40, 0.80, ["300054.SZ", "600206.SH", "600522.SH", "000988.SZ", "002185.SZ", "300655.SZ"], ["电子化学品Ⅱ", "半导体", "通信设备", "通信", "自动化设备"])


def exam6() -> dict[str, Any]:
    as_of = "20260618"
    code = "600522.SH"
    prepare_scores(as_of, ["通信", "通信设备"], [code])
    hist = bars(code, as_of, 8)
    prev5 = hist[hist["trade_date"] < as_of].tail(5)
    cost = float(prev5["close"].max()) if len(prev5) else None
    row = latest_score_row(as_of, code)
    q = quote(code, as_of)
    label = map_label(row)
    return {"exam_id": "exam6", "title": "考题六：已有浮亏仓位的止损判断", "stage": "A", "generated_at": datetime.now().isoformat(timespec="seconds"), "decision_time": f"{as_of} 收盘后", "data_cutoff": as_of, "account": {"asset": 30000, "shares": 300, "cost_rule": "决策日前5个交易日最高收盘价", "cost": cost, "can_watch": False}, "market": market(as_of), "item": {"code": code, "name": stock_name(code), "close": q.get("close") if q else None, "floating_return": (float(q["close"]) / cost - 1) if q and cost else None, "label": label, "row": row}, "decision": {"action": "HOLD_WITH_PROTECTION" if label["can_buy"] or (q and cost and float(q["close"]) / cost - 1 > -0.05) else "REDUCE_RISK", "allow_add": False, "price_stop": "收盘跌破成本下方5%或跌破MA10且不能收回，次日减仓/退出", "logic_stop": "通信板块转弱、核心股走弱、个股不再强于板块", "time_stop": "3个交易日内不能重新站回成本附近，则降低仓位"}, "audit": audit_payload(as_of, [code])}


def simulate_exam6(snapshot: Path) -> dict[str, Any]:
    p = json.loads(snapshot.read_text(encoding="utf-8"))
    code = p["item"]["code"]
    shares = int(p["account"]["shares"])
    cost = float(p["account"]["cost"])
    as_of = p["data_cutoff"]
    dates = date_window(next_trade_date(as_of, 1) or "", 5)
    logs = []
    exit_info = None
    for i, d in enumerate(dates, start=1):
        q = quote(code, d)
        if not q:
            continue
        close = float(q["close"])
        pnl = close / cost - 1
        action = "继续观察"
        if pnl <= -0.05 or i >= 3 and close < cost:
            sp = sell_price(float(q["open"]))
            gross = sp * shares
            exit_info = {"date": d, "sell_price": sp, "cash": gross - fee_sell(gross), "reason": "价格/时间止损"}
            action = "止损退出"
        logs.append({"date": d, "H": i, "open": q["open"], "close": close, "floating_return": pnl, "action": action})
        if exit_info:
            break
    if not exit_info and logs:
        q = quote(code, logs[-1]["date"])
        exit_info = {"date": logs[-1]["date"], "sell_price": float(q["close"]), "cash": float(q["close"]) * shares - fee_sell(float(q["close"]) * shares), "reason": "观察期结束估值"}
    pnl_cash = exit_info["cash"] - cost * shares if exit_info else None
    return {"exam_id": "exam6", "stage": "B", "snapshot_check": verify_snapshot(snapshot), "daily_log": logs, "exit": exit_info, "pnl": pnl_cash, "return_on_position": pnl_cash / (cost * shares) if pnl_cash is not None else None}


def exam4_spec() -> ExamSpec:
    seed = 20260704
    rng = random.Random(seed)
    dates = [d for d in trade_dates() if "20260501" <= d <= "20260615"]
    chosen = rng.choice(dates)
    run_score(chosen)
    daily = read_sql("SELECT ts_code, pct_chg, amount_yuan, close FROM daily WHERE trade_date=? AND close IS NOT NULL", (chosen,))
    daily["pct_chg"] = pd.to_numeric(daily["pct_chg"], errors="coerce")
    daily["amount_yuan"] = pd.to_numeric(daily["amount_yuan"], errors="coerce")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    stock_basic = read_sql("SELECT ts_code, name, list_date FROM stock_basic")
    daily = daily.merge(stock_basic, on="ts_code", how="left")
    daily = daily[daily["close"] * LOT <= 10000 * 0.50]
    daily = daily[~daily["name"].astype(str).str.contains("ST|退", na=False)]
    daily = daily[(daily["list_date"].astype(str) <= "20260315") | daily["list_date"].isna()]
    codes: list[str] = []
    for pool in [daily.sort_values("amount_yuan", ascending=False).head(50), daily.sort_values("pct_chg", ascending=False).head(100), daily.sort_values("pct_chg").head(100)]:
        sample = rng.sample(pool["ts_code"].astype(str).tolist(), min(2, len(pool)))
        codes.extend(sample)
    sectors = sector_scores(chosen).sort_values("score", ascending=False).head(20)["industry_name"].astype(str).tolist()
    run_leader_score(chosen, sectors)
    leaders = pd.read_csv(SCORES / f"leader_scores_{chosen}.csv", dtype={"ts_code": "string"})
    known = set(leaders["ts_code"].astype(str))
    codes = [c for c in codes if c in known]
    top = leaders[leaders["ts_code"].astype(str).isin(daily["ts_code"].astype(str))].sort_values("score", ascending=False)["ts_code"].astype(str).head(20).tolist()
    codes.extend(rng.sample(top, min(2, len(top))))
    codes = list(dict.fromkeys(codes))[:8]
    if len(codes) < 6:
        for c in top:
            if c not in codes:
                codes.append(c)
            if len(codes) >= 6:
                break
    return ExamSpec("exam4", f"考题四：随机弱市或震荡市空仓保护（种子{seed}，日期{chosen}）", chosen, 10000, "低", False, 5, 3, 0.20, 0.50, codes, sectors[:6])


def exam7_spec() -> ExamSpec:
    seed = 20260704
    rng = random.Random(seed + 7)
    candidates = []
    for d in [x for x in trade_dates() if "20260515" <= x <= "20260625"]:
        run_score(d)
        s = sector_scores(d)
        if not s.empty and float(s["score"].max()) >= 75:
            candidates.append(d)
    chosen = rng.choice(candidates)
    s = sector_scores(chosen).sort_values("score", ascending=False)
    top_sector = str(s.iloc[0]["industry_name"])
    run_leader_score(chosen, [top_sector])
    leaders = pd.read_csv(SCORES / f"leader_scores_{chosen}.csv", dtype={"ts_code": "string"}).sort_values("score", ascending=False)
    leaders = leaders[leaders["sector_name"].astype(str) == top_sector].copy()
    codes = leaders["ts_code"].astype(str).head(6).tolist()
    return ExamSpec("exam7", f"考题七：板块强但个股后排识别（种子{seed+7}，日期{chosen}，板块{top_sector}）", chosen, 15000, "中等", False, 3, 2, 0.35, 0.70, codes, [top_sector])


def write_generic_snapshot(payload: dict[str, Any]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{payload['exam_id']}_stageA_{payload['data_cutoff']}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    path.write_text(text, encoding="utf-8")
    path.with_suffix(".sha256").write_text(sha256_file(path), encoding="utf-8")
    return path


def render_report(results: list[dict[str, Any]]) -> str:
    lines = ["# 封闭测试基础设施修复后剩余考题报告", "", f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "", "## 基础设施修复说明", "", "- 修正T日定义：买入成交日为T，H1/H2/H3表示持有第几个交易日。", "- 阶段A固定买入和卖出规则：次日开盘买，固定持有期第N个持有交易日开盘卖；允许提前止损和利润保护。", "- 增加逐交易日持仓日志、止损/利润保护触发、资金使用率、最大浮亏代理。", "- 增加数据审计日志、脚本哈希、评分文件哈希、阶段A快照哈希验证。", "- 未修改评分权重；前三题成绩不替换。", ""]
    total = 0.0
    wins = 0
    closed = 0
    for item in results:
        a = item["stage_a"]
        b = item["stage_b"]
        lines += [f"## {a.get('title')}", "", f"- 决策时间：{a.get('decision_time')}", f"- 市场：{a.get('market',{}).get('score')} / {a.get('market',{}).get('grade')}", f"- 快照验证：{b.get('snapshot_check',{}).get('ok')}", ""]
        if "items" in a:
            lines += ["### 阶段A标签", "", "| 股票 | 代码 | 板块 | 个股分 | 原状态 | 标签 | 可买 | 原因 |", "|---|---|---|---:|---|---|---|---|"]
            for r in a["items"]:
                lines.append(f"| {r['name']} | {r['code']} | {r.get('sector','')} | {r.get('stock_score','-')} | {r.get('raw_status','-')} | {r.get('label')} | {'是' if r.get('can_buy') else '否'} | {r.get('reason')} |")
            lines += ["", "### 阶段B结果", ""]
            lines.append(f"- 投入资金：{b.get('account',{}).get('invested', 0):.2f}")
            lines.append(f"- 账户盈亏：{b.get('account',{}).get('total_pnl', 0):.2f}")
            lines.append(f"- 账户收益率：{b.get('account',{}).get('return_on_account', 0):.2%}")
            lines.append(f"- 最大浮亏代理：{b.get('account',{}).get('max_drawdown_proxy', 0):.2%}")
            total += float(b.get("account", {}).get("total_pnl", 0) or 0)
            if float(b.get("account", {}).get("total_pnl", 0) or 0) > 0:
                wins += 1
            closed += 1
            for tr in b.get("trades", []):
                lines.append(f"- {tr.get('name','')} {tr.get('code','')}：{tr.get('action')}，盈亏 {tr.get('pnl','-')}，退出 {tr.get('exit',{}).get('reason','-')}")
        else:
            lines += ["### 阶段A持仓判断", "", f"- 决策：{a.get('decision',{}).get('action')}", f"- 不允许补仓：{not a.get('decision',{}).get('allow_add', True)}", "", "### 阶段B结果", ""]
            lines.append(f"- 盈亏：{b.get('pnl')}")
            lines.append(f"- 收益率：{b.get('return_on_position')}")
            total += float(b.get("pnl") or 0)
            if float(b.get("pnl") or 0) > 0:
                wins += 1
            closed += 1
        lines += ["", "### 逐日日志摘录", ""]
        if "trades" in b:
            for tr in b.get("trades", []):
                for log in tr.get("daily_log", [])[:6]:
                    lines.append(f"- {tr.get('name','')} {log}")
        else:
            for log in b.get("daily_log", [])[:8]:
                lines.append(f"- {log}")
        lines.append("")
    lines += ["## 剩余考题阶段总评", "", f"- 四题合计盈亏：{total:.2f}", f"- 胜率粗略统计：{wins}/{closed}", "- 本次只验证基础设施和剩余样本，不根据结果调参。", "- 需要等七题总报告后，再区分工程问题、执行规则问题、标签定义问题、评分权重问题和正常概率损失。"]
    return "\n".join(lines)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in [exam3(), exam4_spec(), exam7_spec()]:
        a = make_stage_a(spec)
        path = write_snapshot(a)
        b = simulate_stage_b(path)
        (OUT / f"{a['exam_id']}_stageB.json").write_text(json.dumps(b, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        results.append({"stage_a": a, "stage_b": b})
    a6 = exam6()
    p6 = write_generic_snapshot(a6)
    b6 = simulate_exam6(p6)
    (OUT / "exam6_stageB.json").write_text(json.dumps(b6, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    results.insert(1, {"stage_a": a6, "stage_b": b6})
    report = render_report(results)
    report_path = OUT / "remaining_exam_report_20260704.md"
    report_path.write_text(report, encoding="utf-8")
    print(json.dumps({"report": str(report_path), "items": [x["stage_a"]["exam_id"] for x in results]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
