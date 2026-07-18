from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "walk_forward_2025"
QUESTIONS_JSON = ROOT / "reports" / "tests_2025" / "walk_forward_paths_2025_questions.json"
RESULT_JSON = REPORT_DIR / "WF2025_INTRA_02_result.json"
EXECUTION_JSON = REPORT_DIR / "WF2025_INTRA_02_execution_log.json"
DECISIONS_JSON = REPORT_DIR / "WF2025_INTRA_02_decisions.json"
OUT_JSON = REPORT_DIR / "WF2025_INTRA_02_blocked_trade_review_mvp.json"
OUT_MD = REPORT_DIR / "WF2025_INTRA_02_blocked_trade_review_mvp.md"

SLIPPAGE = 0.001
INITIAL_EQUITY = 60000.0


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def money(value: float) -> float:
    return round(value, 2)


def pct(value: float) -> float:
    return round(value * 100, 2)


def load_prices(path: dict, database_path: str) -> dict[str, dict]:
    uri = f"file:{Path(database_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        prices = {}
        for step in path["daily_steps"]:
            date = step["date"]
            row = conn.execute(
                """
                select trade_date, open, high, low, close, pct_chg
                from daily
                where ts_code=? and trade_date=?
                """,
                ("300300.SZ", date),
            ).fetchone()
            if not row:
                raise RuntimeError(f"missing OHLC for 300300.SZ {date}")
            prices[date] = {
                "date": row[0],
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "pct_chg": float(row[5]),
            }
        return prices
    finally:
        conn.close()


def baseline_curve(decisions: list[dict], prices: dict[str, dict]) -> tuple[list[dict], float]:
    peak = INITIAL_EQUITY
    max_drawdown = 0.0
    rows = []
    for item in decisions:
        pos = item.get("position_after_action") or {}
        shares = int(pos.get("shares") or 0)
        cash = float(item.get("cash_after_action") or 0)
        close = prices[item["date"]]["close"]
        equity = cash + shares * close
        peak = max(peak, equity)
        drawdown = equity / peak - 1 if peak else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        rows.append(
            {
                "date": item["date"],
                "cash": money(cash),
                "shares": shares,
                "close": close,
                "equity": money(equity),
                "drawdown_pct": pct(drawdown),
            }
        )
    return rows, pct(max_drawdown)


def scenario_after_block(
    *,
    blocked_date: str,
    steps: list[str],
    prices: dict[str, dict],
    start_cash: float,
    start_shares: int,
    baseline_peak: float,
) -> dict:
    idx = steps.index(blocked_date)
    if idx + 1 >= len(steps):
        return {"executable": False, "reason": "路径结束日，无下一交易日可执行。"}
    next_date = steps[idx + 1]
    sell_shares = 100 if start_shares >= 200 else start_shares
    execution_price = round(prices[next_date]["open"] * (1 - SLIPPAGE), 3)
    cash = start_cash + sell_shares * execution_price
    shares = start_shares - sell_shares
    peak = baseline_peak
    max_drawdown = 0.0
    rows = []
    for date in steps[idx + 1 :]:
        equity = cash + shares * prices[date]["close"]
        peak = max(peak, equity)
        drawdown = equity / peak - 1 if peak else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        rows.append(
            {
                "date": date,
                "cash": money(cash),
                "shares": shares,
                "close": prices[date]["close"],
                "equity": money(equity),
                "drawdown_pct": pct(drawdown),
            }
        )
    final_equity = rows[-1]["equity"]
    return {
        "executable": True,
        "execution_date": next_date,
        "execution_price": execution_price,
        "sell_shares": sell_shares,
        "trade_count_delta": 1,
        "final_equity": final_equity,
        "final_return_pct": round((final_equity / INITIAL_EQUITY - 1) * 100, 2),
        "max_drawdown_from_existing_peak_pct": pct(max_drawdown),
        "curve": rows,
    }


def scenario_allow_all(
    *,
    blocked_dates: list[str],
    steps: list[str],
    prices: dict[str, dict],
    start_cash: float,
    start_shares: int,
    baseline_peak: float,
) -> dict:
    cash = start_cash
    shares = start_shares
    peak = baseline_peak
    max_drawdown = 0.0
    pending: list[tuple[str, int, str]] = []
    executed = []
    rows = []
    start_idx = steps.index(blocked_dates[0])
    if shares >= 200:
        pending.append((steps[start_idx + 1], 100, blocked_dates[0]))
    for date in steps[start_idx + 1 :]:
        for due, qty, source_date in pending[:]:
            if due == date and shares > 0:
                sell_shares = min(qty, shares)
                execution_price = round(prices[date]["open"] * (1 - SLIPPAGE), 3)
                cash += sell_shares * execution_price
                shares -= sell_shares
                executed.append(
                    {
                        "source_block_date": source_date,
                        "execution_date": date,
                        "execution_price": execution_price,
                        "sell_shares": sell_shares,
                    }
                )
                pending.remove((due, qty, source_date))
        equity = cash + shares * prices[date]["close"]
        peak = max(peak, equity)
        drawdown = equity / peak - 1 if peak else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        rows.append(
            {
                "date": date,
                "cash": money(cash),
                "shares": shares,
                "close": prices[date]["close"],
                "equity": money(equity),
                "drawdown_pct": pct(drawdown),
            }
        )
        if date in blocked_dates and shares >= 200:
            idx = steps.index(date)
            if idx + 1 < len(steps):
                pending.append((steps[idx + 1], 100, date))
    final_equity = rows[-1]["equity"]
    return {
        "executed_relaxed_trades": executed,
        "trade_count_delta": len(executed),
        "final_equity": final_equity,
        "final_return_pct": round((final_equity / INITIAL_EQUITY - 1) * 100, 2),
        "max_drawdown_from_existing_peak_pct": pct(max_drawdown),
        "curve": rows,
    }


def main() -> int:
    questions = read_json(QUESTIONS_JSON)
    path = next(item for item in questions["paths"] if item["path_id"] == "WF2025-INTRA-02")
    prices = load_prices(path, questions["database_path"])
    result = read_json(RESULT_JSON)
    execution_log = read_json(EXECUTION_JSON)["execution_log"]
    decisions = read_json(DECISIONS_JSON)["decisions"]
    blocked = [item for item in execution_log if item.get("action") == "BLOCKED_TRADE"]
    steps = [step["date"] for step in path["daily_steps"]]
    curve, baseline_mdd = baseline_curve(decisions, prices)
    baseline_peak_before_blocks = max(item["equity"] for item in curve if item["date"] <= blocked[0]["date"])
    baseline_final_equity = curve[-1]["equity"]

    decision_by_date = {item["date"]: item for item in decisions}
    reviews = []
    for item in blocked:
        decision = decision_by_date[item["date"]]
        pos = decision.get("position_after_action") or {}
        close = prices[item["date"]]["close"]
        one = scenario_after_block(
            blocked_date=item["date"],
            steps=steps,
            prices=prices,
            start_cash=float(item["cash_after"]),
            start_shares=int(pos.get("shares") or 0),
            baseline_peak=baseline_peak_before_blocks,
        )
        final_delta = round(one["final_return_pct"] - result["final_return_pct"], 2)
        equity_delta = money(one["final_equity"] - baseline_final_equity)
        reviews.append(
            {
                "date": item["date"],
                "ts_code": item["ts_code"],
                "name": item["name"],
                "intended_action": item["intended_action"],
                "final_action": item["final_action"],
                "signal_strength": item["signal_strength"],
                "trade_block_reason": item["trade_block_reason"],
                "blocked_reason": item["reason"],
                "close_price_on_block_date": close,
                "position_shares_after_day": int(pos.get("shares") or 0),
                "position_market_value_after_day": money(float(pos.get("market_value") or 0)),
                "single_position_ratio_after_day": decision.get("single_position_ratio"),
                "profit_protection": decision.get("profit_protection"),
                "stop_loss": decision.get("stop_loss"),
                "if_relaxed_once": {
                    **one,
                    "final_return_delta_pct_vs_baseline": final_delta,
                    "final_equity_delta_vs_baseline": equity_delta,
                },
                "verdict": "需要新增更精细规则",
                "verdict_reason": (
                    "信号强度为 strong_trade_allowed，且意图是风险减仓；用交易密度一刀切拦截不宜直接判为合理。"
                    "但事后小对照显示放宽会减少本段最终收益，且最大回撤发生在拦截前，不能据此直接改成全面放宽。"
                ),
            }
        )

    all_relaxed = scenario_allow_all(
        blocked_dates=[item["date"] for item in blocked],
        steps=steps,
        prices=prices,
        start_cash=float(blocked[0]["cash_after"]),
        start_shares=int((decision_by_date[blocked[0]["date"]].get("position_after_action") or {}).get("shares") or 0),
        baseline_peak=baseline_peak_before_blocks,
    )

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "path_id": "WF2025-INTRA-02",
        "scope": "INTRA-02 被拦截交易意图复查 MVP；不重跑全部路径，不改评分权重，不接账户，不自动交易，不接消息面。",
        "data_boundary": "仅使用 questions 可见路径、既有 INTRA-02 输出和路径完成后的 OHLC 小对照；validation_private 不参与日内决策生成。",
        "baseline": {
            "final_return_pct": result["final_return_pct"],
            "max_drawdown_pct": result["max_drawdown_pct"],
            "trade_count": result["trade_count"],
            "blocked_trade_count": result["blocked_trade_count"],
            "final_equity": baseline_final_equity,
            "max_drawdown_recomputed_pct": baseline_mdd,
        },
        "blocked_reviews": reviews,
        "allow_all_strong_reduce_counterfactual": {
            **all_relaxed,
            "final_return_delta_pct_vs_baseline": round(all_relaxed["final_return_pct"] - result["final_return_pct"], 2),
            "final_equity_delta_vs_baseline": money(all_relaxed["final_equity"] - baseline_final_equity),
        },
        "conclusion": {
            "overall_verdict": "需要新增更精细规则",
            "keep_block": False,
            "relax_once": False,
            "add_finer_rule": True,
            "summary": (
                "4 个拦截均不是 medium/weak 买入冲动，而是同一持仓的 strong_trade_allowed 风险减仓意图。"
                "现有交易密度规则对 REDUCE 风险动作和 BUY 新开仓动作没有足够区分，存在过度保守嫌疑。"
                "但小对照显示，如果在 2025-11-07 至 2025-11-12 放宽，最终收益会低于基线；最大回撤仍由 2025-11-06 形成，放宽不能改善本路径最大回撤。"
                "因此本轮不直接放宽规则，建议后续新增更精细规则：强风险减仓可进入人工复核或单次例外池，但不得与新买入共用同一个密度阈值。"
            ),
        },
    }

    write_json(OUT_JSON, payload)
    lines = [
        "# WF2025-INTRA-02 被拦截交易意图复查 MVP",
        "",
        f"- 生成时间：{payload['generated_at']}",
        "- 范围：只复查 INTRA-02 的 4 个 needs_rule_review，不重跑全部路径。",
        "- 边界：不进入 FULL_PIPELINE_SELECTION_WALK_FORWARD；不改评分权重；不接真实账户；不自动交易；不接消息面。",
        "- 数据边界：使用 questions 可见路径、既有 INTRA-02 输出和路径完成后的 OHLC 小对照；validation_private 不参与日内决策生成。",
        "",
        "## 基线",
        "",
        f"- 最终收益率：{result['final_return_pct']}%",
        f"- 最大回撤：{result['max_drawdown_pct']}%",
        f"- 真实交易次数：{result['trade_count']}（BLOCKED_TRADE 未计入）",
        f"- BLOCKED_TRADE：{result['blocked_trade_count']} 个，均为 needs_rule_review",
        "",
        "## 逐笔复查",
        "",
        "| 日期 | 代码 | 名称 | 意图 | 收盘价 | 仓位股数 | 单票仓位 | 信号强度 | 拦截原因 | 若单次放宽后收益 | 收益变化 | 交易次数变化 | 结论 |",
        "| -- | -- | -- | -- | --: | --: | --: | -- | -- | --: | --: | --: | -- |",
    ]
    for item in reviews:
        sim = item["if_relaxed_once"]
        lines.append(
            f"| {item['date']} | {item['ts_code']} | {item['name']} | {item['intended_action']} | "
            f"{item['close_price_on_block_date']} | {item['position_shares_after_day']} | "
            f"{round(float(item['single_position_ratio_after_day']) * 100, 2)}% | {item['signal_strength']} | "
            f"{item['trade_block_reason']} | {sim['final_return_pct']}% | "
            f"{sim['final_return_delta_pct_vs_baseline']}pct | +{sim['trade_count_delta']} | {item['verdict']} |"
        )
    lines.extend(
        [
            "",
            "## 小对照估算",
            "",
            "- 单次放宽口径：将该日的 REDUCE 意图保留为次一交易日开盘减仓 100 股，其他规则不改。",
            "- 全部放宽口径：在同一持仓仍满足 strong REDUCE 且剩余股数不少于 200 股时，最多形成 2 次额外减仓。",
            f"- 全部放宽后估算收益率：{payload['allow_all_strong_reduce_counterfactual']['final_return_pct']}%，较基线 {payload['allow_all_strong_reduce_counterfactual']['final_return_delta_pct_vs_baseline']}pct。",
            f"- 全部放宽后估算交易次数：{result['trade_count'] + payload['allow_all_strong_reduce_counterfactual']['trade_count_delta']}，较基线 +{payload['allow_all_strong_reduce_counterfactual']['trade_count_delta']}。",
            f"- 最大回撤：基线为 {result['max_drawdown_pct']}%；小对照未改善该最大回撤，因为最大回撤发生在 2025-11-06，早于这 4 个拦截的可执行影响。",
            "",
            "## 结论",
            "",
            "- 不是简单“保留拦截”：4 个信号都是 strong_trade_allowed 风险减仓，被同一个交易密度阈值拦截，存在过度保守嫌疑。",
            "- 也不建议本轮直接“放宽一次”：事后小对照显示放宽会降低本路径最终收益，且不能改善最大回撤。",
            "- 本轮输出结论：需要新增更精细规则。建议后续把 REDUCE/SELL 风险动作与 BUY 新开仓动作分开计数；strong REDUCE 可进入人工复核或单次例外池，但不能直接全面豁免。",
            "",
            "边界说明：以上为报告层复查和小对照估算，不构成交易指令，未连接真实账户，也未改变主回测规则。",
        ]
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"markdown": str(OUT_MD), "json": str(OUT_JSON), "overall_verdict": "需要新增更精细规则"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
