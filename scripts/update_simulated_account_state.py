from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
STATE_DIR = BASE_DIR / "state"
DAILY_DIR = BASE_DIR / "daily"
INPUT_DIR = BASE_DIR / "input"
REVIEW_DIR = BASE_DIR / "review"

ACCOUNT_STATE_FILE = STATE_DIR / "simulated_account_state.json"
SNAPSHOT_DIR = STATE_DIR / "snapshots"
TRADE_LOG_DIR = STATE_DIR / "trade_logs"
MARKET_DATA_DIR = INPUT_DIR / "market_data"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_dirs() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    TRADE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)


def get_price_map(market_data: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in market_data.get("target_symbols_ohlc", []):
        ts_code = item.get("ts_code")
        price = item.get("mark_price")
        if price is None:
            price = item.get("close")
        if ts_code and price is not None:
            result[ts_code] = float(price)
    return result


def recompute_account(state: dict[str, Any], price_map: dict[str, float]) -> None:
    total_market_value = 0.0
    total_unrealized = 0.0
    flags = list(state.get("account_risk_flags", []))
    human_review_items = list(state.get("human_review_items", []))
    missing_symbols: list[str] = []
    for position in state.get("positions", []):
        ts_code = position.get("ts_code")
        shares = int(position.get("shares", 0))
        cost_basis = float(position.get("cost_basis", 0))
        if ts_code in price_map:
            mark_price = float(price_map[ts_code])
            position["mark_price"] = mark_price
        else:
            mark_price = float(position.get("mark_price", cost_basis))
            missing_symbols.append(str(ts_code or ""))
            if "missing_price" not in flags:
                flags.append("missing_price")
        market_value = round(shares * mark_price, 4)
        unrealized = round((mark_price - cost_basis) * shares, 4)
        position["market_value"] = market_value
        position["unrealized_pnl"] = unrealized
        total_market_value += market_value
        total_unrealized += unrealized

    for ts_code in missing_symbols:
        review_text = f"{ts_code} missing real market price; valuation update skipped and manual review required"
        if review_text not in human_review_items:
            human_review_items.append(review_text)

    total_equity = round(float(state.get("cash", 0)) + total_market_value, 4)
    initial_cash = float(state.get("initial_cash", total_equity))
    previous_total_equity = float(state.get("previous_total_equity", initial_cash))
    daily_pnl = round(total_equity - previous_total_equity, 4)
    daily_pnl_ratio = 0.0 if previous_total_equity == 0 else round(daily_pnl / previous_total_equity, 6)
    cumulative_pnl = round(total_equity - initial_cash, 4)
    cumulative_pnl_ratio = 0.0 if initial_cash == 0 else round(cumulative_pnl / initial_cash, 6)

    state["unrealized_pnl"] = round(total_unrealized, 4)
    state["total_equity"] = total_equity
    state["daily_pnl"] = daily_pnl
    state["daily_pnl_ratio"] = daily_pnl_ratio
    state["cumulative_pnl"] = cumulative_pnl
    state["cumulative_pnl_ratio"] = cumulative_pnl_ratio
    state["account_risk_flags"] = flags
    state["human_review_items"] = human_review_items


def execute_observe_or_hold(
    state: dict[str, Any],
    price_map: dict[str, float],
    action: str,
) -> tuple[str, str, dict[str, Any]]:
    recompute_account(state, price_map)
    if action == "HOLD":
        return "HOLD", "", {"price": None, "shares": 0}
    return "OBSERVE", "", {"price": None, "shares": 0}


def execute_buy(
    state: dict[str, Any],
    report: dict[str, Any],
    price_map: dict[str, float],
) -> tuple[str, str, dict[str, Any]]:
    candidate_ts_code = report.get("candidate_ts_code")
    candidate_name = report.get("candidate_name", "")
    if not candidate_ts_code:
        recompute_account(state, price_map)
        return "OBSERVE", "missing_candidate_ts_code", {"price": None, "shares": 0}

    price = price_map.get(candidate_ts_code)
    if price is None:
        recompute_account(state, price_map)
        return "OBSERVE", "missing_mark_price", {"price": None, "shares": 0}

    if state.get("new_buy_count_today", 0) >= state.get("max_new_buy_per_day", 0):
        recompute_account(state, price_map)
        return "OBSERVE", "max_new_buy_per_day_reached", {"price": price, "shares": 0}
    if state.get("trade_count_today", 0) >= state.get("max_total_trades_per_day", 0):
        recompute_account(state, price_map)
        return "OBSERVE", "max_total_trades_per_day_reached", {"price": price, "shares": 0}

    lot_size = int(state.get("lot_size", 100))
    requested_shares_raw = report.get("suggested_shares", report.get("requested_shares"))
    shares_to_buy = lot_size
    if requested_shares_raw is not None:
        try:
            parsed_requested_shares = int(requested_shares_raw)
            if parsed_requested_shares > 0 and parsed_requested_shares % lot_size == 0:
                shares_to_buy = parsed_requested_shares
        except (TypeError, ValueError):
            pass

    lot_value = round(price * shares_to_buy, 4)
    single_limit = round(float(state.get("total_equity", 0)) * float(state.get("max_position_per_stock", 0)), 4)
    total_limit = round(float(state.get("total_equity", 0)) * float(state.get("max_total_position", 0)), 4)
    current_market_value = sum(float(item.get("market_value", 0)) for item in state.get("positions", []))

    if lot_value > single_limit:
        recompute_account(state, price_map)
        return "OBSERVE", "lot_value_exceeds_position_limit", {"price": price, "shares": 0}
    if current_market_value + lot_value > total_limit:
        recompute_account(state, price_map)
        return "OBSERVE", "buy_exceeds_total_position_limit", {"price": price, "shares": 0}
    if float(state.get("cash", 0)) < lot_value:
        recompute_account(state, price_map)
        return "OBSERVE", "insufficient_cash", {"price": price, "shares": 0}

    state["cash"] = round(float(state["cash"]) - lot_value, 4)
    position = {
        "ts_code": candidate_ts_code,
        "name": candidate_name,
        "shares": shares_to_buy,
        "cost_basis": price,
        "mark_price": price,
        "market_value": lot_value,
        "unrealized_pnl": 0.0,
    }
    state.setdefault("positions", []).append(position)
    state["trade_count_today"] = int(state.get("trade_count_today", 0)) + 1
    state["new_buy_count_today"] = int(state.get("new_buy_count_today", 0)) + 1
    recompute_account(state, price_map)
    return "BUY", "", {"price": price, "shares": shares_to_buy}


def execute_reduce_or_sell(
    state: dict[str, Any],
    report: dict[str, Any],
    price_map: dict[str, float],
    action: str,
) -> tuple[str, str, dict[str, Any]]:
    candidate_ts_code = report.get("candidate_ts_code")
    positions = state.get("positions", [])
    position = None
    for item in positions:
        if item.get("ts_code") == candidate_ts_code:
            position = item
            break
    if position is None:
        recompute_account(state, price_map)
        return "OBSERVE", "no_position_to_reduce_or_sell", {"price": None, "shares": 0}

    price = price_map.get(candidate_ts_code)
    if price is None:
        recompute_account(state, price_map)
        return "OBSERVE", "missing_mark_price", {"price": None, "shares": 0}

    shares_owned = int(position.get("shares", 0))
    if shares_owned <= 0:
        recompute_account(state, price_map)
        return "OBSERVE", "no_position_to_reduce_or_sell", {"price": None, "shares": 0}

    if action == "SELL":
        shares_to_sell = shares_owned
    else:
        shares_to_sell = max(100, shares_owned // 2)
        shares_to_sell = min(shares_to_sell, shares_owned)

    proceeds = round(price * shares_to_sell, 4)
    realized_delta = round((price - float(position.get("cost_basis", 0))) * shares_to_sell, 4)
    state["cash"] = round(float(state.get("cash", 0)) + proceeds, 4)
    state["realized_pnl"] = round(float(state.get("realized_pnl", 0)) + realized_delta, 4)
    state["trade_count_today"] = int(state.get("trade_count_today", 0)) + 1

    remaining = shares_owned - shares_to_sell
    if remaining <= 0:
        positions.remove(position)
    else:
        position["shares"] = remaining
        position["mark_price"] = price

    recompute_account(state, price_map)
    return action, "", {"price": price, "shares": shares_to_sell}


def execute_needs_human_review(state: dict[str, Any], report: dict[str, Any], price_map: dict[str, float]) -> tuple[str, str, list[str], dict[str, Any]]:
    recompute_account(state, price_map)
    human_review_items = list(state.get("human_review_items", []))
    reason = report.get("needs_human_review_reason") or "needs_human_review"
    human_review_items.append(reason)
    state["human_review_items"] = human_review_items
    return "NEEDS_HUMAN_REVIEW", "", human_review_items, {"price": None, "shares": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description="Update local simulated account state")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--state-file", default=str(ACCOUNT_STATE_FILE))
    parser.add_argument("--output-state-file", default="")
    parser.add_argument("--snapshot-file", default="")
    parser.add_argument("--trade-log-file", default="")
    parser.add_argument("--report-json-file", default="")
    parser.add_argument("--report-md-file", default="")
    parser.add_argument("--market-data-file", default="")
    parser.add_argument("--daily-report-file", default="")
    args = parser.parse_args()

    ensure_dirs()

    trade_date = args.trade_date
    state_file = Path(args.state_file)
    output_state_file = Path(args.output_state_file) if args.output_state_file else state_file
    market_data_file = Path(args.market_data_file) if args.market_data_file else MARKET_DATA_DIR / f"market_data_{trade_date}.json"
    daily_report_file = Path(args.daily_report_file) if args.daily_report_file else DAILY_DIR / f"simulated_live_v1_daily_report_{trade_date}.json"
    snapshot_file = Path(args.snapshot_file) if args.snapshot_file else SNAPSHOT_DIR / f"simulated_account_state_{trade_date}.json"
    trade_log_file = Path(args.trade_log_file) if args.trade_log_file else TRADE_LOG_DIR / f"simulated_trade_log_{trade_date}.json"
    report_json_file = Path(args.report_json_file) if args.report_json_file else REVIEW_DIR / f"account_state_update_{trade_date}.json"
    report_md_file = Path(args.report_md_file) if args.report_md_file else REVIEW_DIR / f"account_state_update_{trade_date}.md"
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    trade_log_file.parent.mkdir(parents=True, exist_ok=True)
    report_json_file.parent.mkdir(parents=True, exist_ok=True)
    report_md_file.parent.mkdir(parents=True, exist_ok=True)

    state_before = dict(read_json(state_file))
    state_after = deepcopy(state_before)
    market_data = dict(read_json(market_data_file))
    daily_report = dict(read_json(daily_report_file))
    price_map = get_price_map(market_data)

    cash_before = float(state_before.get("cash", 0))
    total_equity_before = float(state_before.get("total_equity", 0))
    positions_count_before = len(state_before.get("positions", []))
    final_user_action = str(daily_report.get("final_user_action", "OBSERVE"))
    block_reason = ""
    human_review_items: list[str] = list(state_before.get("human_review_items", []))
    execution_meta = {"price": None, "shares": 0}

    state_after["trade_count_today"] = 0
    state_after["new_buy_count_today"] = 0
    state_after["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state_after["previous_total_equity"] = total_equity_before or float(state_after.get("initial_cash", 0))

    if final_user_action == "BUY":
        action_executed, block_reason, execution_meta = execute_buy(state_after, daily_report, price_map)
    elif final_user_action == "REDUCE":
        action_executed, block_reason, execution_meta = execute_reduce_or_sell(state_after, daily_report, price_map, "REDUCE")
    elif final_user_action == "SELL":
        action_executed, block_reason, execution_meta = execute_reduce_or_sell(state_after, daily_report, price_map, "SELL")
    elif final_user_action == "HOLD":
        action_executed, block_reason, execution_meta = execute_observe_or_hold(state_after, price_map, "HOLD")
    elif final_user_action == "NEEDS_HUMAN_REVIEW":
        action_executed, block_reason, human_review_items, execution_meta = execute_needs_human_review(state_after, daily_report, price_map)
    else:
        action_executed, block_reason, execution_meta = execute_observe_or_hold(state_after, price_map, "OBSERVE")

    state_after["real_account_connected"] = False
    state_after["auto_trading_enabled"] = False
    state_after["news_module_enabled"] = False

    write_json(output_state_file, state_after)
    write_json(snapshot_file, state_after)

    trade_log = {
        "trade_date": trade_date,
        "action_requested": final_user_action,
        "action_executed": action_executed,
        "ts_code": daily_report.get("candidate_ts_code"),
        "name": daily_report.get("candidate_name"),
        "price": execution_meta["price"],
        "shares": execution_meta["shares"],
        "cash_before": cash_before,
        "cash_after": state_after.get("cash"),
        "total_equity_before": total_equity_before,
        "total_equity_after": state_after.get("total_equity"),
        "previous_total_equity": state_after.get("previous_total_equity"),
        "block_reason": block_reason,
        "human_review_reason": human_review_items,
        "note": "local simulated account update only; never connected to real account",
    }
    write_json(trade_log_file, trade_log)

    report = {
        "account_state_update_completed": True,
        "trade_date": trade_date,
        "final_user_action": final_user_action,
        "action_executed": action_executed,
        "cash_before": cash_before,
        "cash_after": state_after.get("cash"),
        "total_equity_before": total_equity_before,
        "total_equity_after": state_after.get("total_equity"),
        "previous_total_equity": state_after.get("previous_total_equity"),
        "daily_pnl": state_after.get("daily_pnl"),
        "daily_pnl_ratio": state_after.get("daily_pnl_ratio"),
        "cumulative_pnl": state_after.get("cumulative_pnl"),
        "cumulative_pnl_ratio": state_after.get("cumulative_pnl_ratio"),
        "positions_count_before": positions_count_before,
        "positions_count_after": len(state_after.get("positions", [])),
        "trade_count_today": state_after.get("trade_count_today"),
        "new_buy_count_today": state_after.get("new_buy_count_today"),
        "block_reason": block_reason,
        "human_review_items": state_after.get("human_review_items", human_review_items),
        "account_risk_flags": state_after.get("account_risk_flags", []),
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "recommended_next_step": "connect account updater to future dated daily reports with manual sample prices or real local market files",
    }
    write_json(report_json_file, report)
    report_md_file.write_text(
        f"""# account_state_update_{trade_date}

- account_state_update_completed: {report['account_state_update_completed']}
- trade_date: {report['trade_date']}
- final_user_action: {report['final_user_action']}
- action_executed: {report['action_executed']}
- cash_before: {report['cash_before']}
- cash_after: {report['cash_after']}
- total_equity_before: {report['total_equity_before']}
- total_equity_after: {report['total_equity_after']}
- previous_total_equity: {report['previous_total_equity']}
- daily_pnl: {report['daily_pnl']}
- daily_pnl_ratio: {report['daily_pnl_ratio']}
- cumulative_pnl: {report['cumulative_pnl']}
- cumulative_pnl_ratio: {report['cumulative_pnl_ratio']}
- positions_count_before: {report['positions_count_before']}
- positions_count_after: {report['positions_count_after']}
- trade_count_today: {report['trade_count_today']}
- new_buy_count_today: {report['new_buy_count_today']}
- block_reason: {report['block_reason']}
- human_review_items: {report['human_review_items']}
- account_risk_flags: {report['account_risk_flags']}
- real_account_connected: {report['real_account_connected']}
- auto_trading_enabled: {report['auto_trading_enabled']}
- full_pipeline_enabled: {report['full_pipeline_enabled']}
- news_module_enabled: {report['news_module_enabled']}
- recommended_next_step: {report['recommended_next_step']}
""",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "account_state_update_completed": True,
                "trade_date": trade_date,
                "action_executed": action_executed,
                "state_file_used": str(state_file),
                "output_state_file": str(output_state_file),
                "snapshot_file": str(snapshot_file),
                "trade_log_file": str(trade_log_file),
                "report_json_file": str(report_json_file),
                "report_md_file": str(report_md_file),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
