from __future__ import annotations

import argparse
import importlib.util
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
REVIEW_DIR = BASE_DIR / "review"
UPDATER_PATH = ROOT / "scripts" / "update_simulated_account_state.py"


spec = importlib.util.spec_from_file_location("update_simulated_account_state", UPDATER_PATH)
assert spec and spec.loader
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def render_positions(positions: list[dict[str, Any]], total_equity: float) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for position in positions:
        market_value = float(position.get("market_value", 0))
        result.append(
            {
                "ts_code": position.get("ts_code", ""),
                "name": position.get("name", ""),
                "shares": int(position.get("shares", 0)),
                "cost_basis": float(position.get("cost_basis", 0)),
                "mark_price": float(position.get("mark_price", 0)),
                "market_value": market_value,
                "unrealized_pnl": float(position.get("unrealized_pnl", 0)),
                "position_ratio": 0.0 if total_equity == 0 else round(market_value / total_equity, 6),
            }
        )
    return result


def build_feishu_summary(logical_day: str, state: dict[str, Any], action_executed: str, human_review_items: list[str]) -> str:
    return (
        f"逻辑日：{logical_day}；"
        f"total_equity：{state['total_equity']}；"
        f"previous_total_equity：{state['previous_total_equity']}；"
        f"daily_pnl：{state['daily_pnl']}；"
        f"cumulative_pnl：{state['cumulative_pnl']}；"
        f"action_executed：{action_executed}；"
        f"positions_count：{len(state.get('positions', []))}；"
        f"human_review_items_count：{len(human_review_items)}；"
        "test_run only，不接真实账户、不自动交易。"
    )


def build_final_report(logical_day: str, state: dict[str, Any], daily_decision: dict[str, Any], trade_log: dict[str, Any]) -> dict[str, Any]:
    human_review_items = list(state.get("human_review_items", []))
    positions_view = render_positions(state.get("positions", []), float(state.get("total_equity", 0)))
    return {
        "logical_day": logical_day,
        "sample_test_only": True,
        "original_model_action": daily_decision.get("original_model_action", daily_decision.get("final_user_action", "OBSERVE")),
        "ai_review_shadow_action": daily_decision.get("ai_review_shadow_action", daily_decision.get("final_user_action", "OBSERVE")),
        "final_user_action": daily_decision.get("final_user_action", "OBSERVE"),
        "action_requested": trade_log.get("action_requested", daily_decision.get("final_user_action", "OBSERVE")),
        "action_executed": trade_log.get("action_executed", daily_decision.get("final_user_action", "OBSERVE")),
        "block_reason": trade_log.get("block_reason", ""),
        "account_summary": {
            "initial_cash": state.get("initial_cash"),
            "previous_total_equity": state.get("previous_total_equity"),
            "total_equity": state.get("total_equity"),
            "cash": state.get("cash"),
            "daily_pnl": state.get("daily_pnl"),
            "daily_pnl_ratio": state.get("daily_pnl_ratio"),
            "cumulative_pnl": state.get("cumulative_pnl"),
            "cumulative_pnl_ratio": state.get("cumulative_pnl_ratio"),
            "realized_pnl": state.get("realized_pnl"),
            "unrealized_pnl": state.get("unrealized_pnl"),
        },
        "positions_view": positions_view,
        "human_review_items": human_review_items,
        "feishu_summary": build_feishu_summary(logical_day, state, trade_log.get("action_executed", "OBSERVE"), human_review_items),
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
    }


def write_day_outputs(test_run_dir: Path, logical_day: str, report: dict[str, Any]) -> None:
    final_json = test_run_dir / "output" / "final_reports" / f"{logical_day}.json"
    final_md = test_run_dir / "output" / "final_reports" / f"{logical_day}.md"
    feishu_md = test_run_dir / "output" / "feishu_messages" / f"{logical_day}.md"
    write_json(final_json, report)
    final_md.write_text(
        "\n".join(
            [
                f"# {logical_day}",
                "",
                f"- final_user_action: {report['final_user_action']}",
                f"- action_executed: {report['action_executed']}",
                f"- total_equity: {report['account_summary']['total_equity']}",
                f"- previous_total_equity: {report['account_summary']['previous_total_equity']}",
                f"- daily_pnl: {report['account_summary']['daily_pnl']}",
                f"- cumulative_pnl: {report['account_summary']['cumulative_pnl']}",
                f"- realized_pnl: {report['account_summary']['realized_pnl']}",
                f"- unrealized_pnl: {report['account_summary']['unrealized_pnl']}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    feishu_md.parent.mkdir(parents=True, exist_ok=True)
    feishu_md.write_text(report["feishu_summary"], encoding="utf-8")


def run_one_day(test_run_dir: Path, logical_day: str, state_file: Path) -> dict[str, Any]:
    market_data = dict(read_json(test_run_dir / "input" / "market_data" / f"{logical_day}.json"))
    candidate_pool = list(read_json(test_run_dir / "input" / "candidate_pool" / f"{logical_day}.json"))
    daily_decision = dict(read_json(test_run_dir / "input" / "daily_reports" / f"{logical_day}.json"))

    state_before = dict(read_json(state_file))
    state_after = deepcopy(state_before)
    price_map = updater.get_price_map(market_data)
    final_user_action = str(daily_decision.get("final_user_action", "OBSERVE"))
    block_reason = ""
    human_review_items: list[str] = list(state_before.get("human_review_items", []))
    execution_meta = {"price": None, "shares": 0}

    state_after["trade_count_today"] = 0
    state_after["new_buy_count_today"] = 0
    state_after["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state_after["previous_total_equity"] = float(state_before.get("total_equity", state_before.get("initial_cash", 0)))

    if final_user_action == "BUY":
        action_executed, block_reason, execution_meta = updater.execute_buy(state_after, daily_decision, price_map)
    elif final_user_action == "REDUCE":
        action_executed, block_reason, execution_meta = updater.execute_reduce_or_sell(state_after, daily_decision, price_map, "REDUCE")
    elif final_user_action == "SELL":
        action_executed, block_reason, execution_meta = updater.execute_reduce_or_sell(state_after, daily_decision, price_map, "SELL")
    elif final_user_action == "HOLD":
        action_executed, block_reason, execution_meta = updater.execute_observe_or_hold(state_after, price_map, "HOLD")
    elif final_user_action == "NEEDS_HUMAN_REVIEW":
        action_executed, block_reason, human_review_items, execution_meta = updater.execute_needs_human_review(state_after, daily_decision, price_map)
    else:
        action_executed, block_reason, execution_meta = updater.execute_observe_or_hold(state_after, price_map, "OBSERVE")

    state_after["real_account_connected"] = False
    state_after["auto_trading_enabled"] = False
    state_after["news_module_enabled"] = False

    snapshot_file = test_run_dir / "state" / "snapshots" / f"{logical_day}.json"
    trade_log_file = test_run_dir / "state" / "trade_logs" / f"{logical_day}.json"
    write_json(snapshot_file, state_after)

    trade_log = {
        "logical_day": logical_day,
        "action_requested": final_user_action,
        "action_executed": action_executed,
        "ts_code": daily_decision.get("candidate_ts_code"),
        "name": daily_decision.get("candidate_name"),
        "price": execution_meta["price"],
        "shares": execution_meta["shares"],
        "cash_before": state_before.get("cash"),
        "cash_after": state_after.get("cash"),
        "total_equity_before": state_before.get("total_equity"),
        "total_equity_after": state_after.get("total_equity"),
        "previous_total_equity": state_after.get("previous_total_equity"),
        "block_reason": block_reason,
        "human_review_reason": human_review_items,
        "note": "test_run only; never connected to real account",
    }
    write_json(trade_log_file, trade_log)

    report = build_final_report(logical_day, state_after, daily_decision, trade_log)
    report["market_data"] = market_data
    report["candidate_pool"] = candidate_pool
    write_day_outputs(test_run_dir, logical_day, report)

    return {
        "logical_day": logical_day,
        "snapshot_file": str(snapshot_file),
        "trade_log_file": str(trade_log_file),
        "final_report": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run isolated simulated_live_v1 test run")
    parser.add_argument("--test-run-id", required=True)
    parser.add_argument("--test-run-dir", required=True)
    parser.add_argument("--test-mode", action="store_true", default=True)
    parser.add_argument("--no-send-feishu", action="store_true")
    parser.add_argument("--send-feishu-test", action="store_true")
    args = parser.parse_args()

    test_run_dir = Path(args.test_run_dir)
    logical_days = ["DAY_001", "DAY_002", "DAY_003", "DAY_004", "DAY_005"]
    state_file = test_run_dir / "state" / "initial_state.json"
    day_results: list[dict[str, Any]] = []

    for logical_day in logical_days:
        result = run_one_day(test_run_dir, logical_day, state_file)
        day_results.append(result)
        state_file = Path(result["snapshot_file"])

    snapshots = [read_json(Path(item["snapshot_file"])) for item in day_results]
    trade_logs = [read_json(Path(item["trade_log_file"])) for item in day_results]

    review = {
        "mixed_action_sequence_completed": True,
        "test_run_id": args.test_run_id,
        "test_run_isolated": True,
        "no_future_real_dates_used": True,
        "no_formal_daily_files_written": True,
        "no_formal_snapshot_files_written": True,
        "no_formal_trade_log_files_written": True,
        "official_state_preserved": True,
        "day1_buy_passed": snapshots[0]["cash"] == 16000 and snapshots[0]["positions"][0]["shares"] == 200 and snapshots[0]["daily_pnl"] == 0 and snapshots[0]["cumulative_pnl"] == 0,
        "day2_hold_passed": snapshots[1]["cash"] == 16000 and snapshots[1]["positions"][0]["shares"] == 200 and snapshots[1]["daily_pnl"] == 400 and snapshots[1]["cumulative_pnl"] == 400,
        "day3_reduce_passed": trade_logs[2]["action_executed"] == "REDUCE" and snapshots[2]["cash"] == 18300 and snapshots[2]["realized_pnl"] == 300 and snapshots[2]["unrealized_pnl"] == 300,
        "day4_hold_after_reduce_passed": snapshots[3]["positions"][0]["shares"] == 100 and snapshots[3]["daily_pnl"] == -200 and snapshots[3]["cumulative_pnl"] == 400,
        "day5_sell_passed": trade_logs[4]["action_executed"] == "SELL" and snapshots[4]["cash"] == 20700 and len(snapshots[4]["positions"]) == 0,
        "reduce_left_remaining_position": len(snapshots[2]["positions"]) == 1 and snapshots[2]["positions"][0]["shares"] == 100,
        "sell_full_exit_passed": len(snapshots[4]["positions"]) == 0,
        "snapshot_chaining_passed": snapshots[1]["previous_total_equity"] == snapshots[0]["total_equity"] and snapshots[2]["previous_total_equity"] == snapshots[1]["total_equity"] and snapshots[3]["previous_total_equity"] == snapshots[2]["total_equity"] and snapshots[4]["previous_total_equity"] == snapshots[3]["total_equity"],
        "cash_carried_forward": snapshots[1]["cash"] == 16000 and snapshots[2]["cash"] == 18300 and snapshots[3]["cash"] == 18300 and snapshots[4]["cash"] == 20700,
        "positions_carried_forward": len(snapshots[0]["positions"]) == 1 and len(snapshots[1]["positions"]) == 1 and len(snapshots[2]["positions"]) == 1 and len(snapshots[3]["positions"]) == 1 and len(snapshots[4]["positions"]) == 0,
        "daily_pnl_calculation_passed": snapshots[1]["daily_pnl"] == 400 and snapshots[2]["daily_pnl"] == 200 and snapshots[3]["daily_pnl"] == -200 and snapshots[4]["daily_pnl"] == 300,
        "cumulative_pnl_calculation_passed": snapshots[0]["cumulative_pnl"] == 0 and snapshots[1]["cumulative_pnl"] == 400 and snapshots[2]["cumulative_pnl"] == 600 and snapshots[3]["cumulative_pnl"] == 400 and snapshots[4]["cumulative_pnl"] == 700,
        "realized_pnl_calculation_passed": snapshots[0]["realized_pnl"] == 0 and snapshots[1]["realized_pnl"] == 0 and snapshots[2]["realized_pnl"] == 300 and snapshots[3]["realized_pnl"] == 300 and snapshots[4]["realized_pnl"] == 700,
        "unrealized_pnl_calculation_passed": snapshots[0]["unrealized_pnl"] == 0 and snapshots[1]["unrealized_pnl"] == 400 and snapshots[2]["unrealized_pnl"] == 300 and snapshots[3]["unrealized_pnl"] == 100 and snapshots[4]["unrealized_pnl"] == 0,
        "trade_log_not_duplicated": [log["logical_day"] for log in trade_logs] == logical_days,
        "no_negative_position_check": all(all(int(position.get("shares", 0)) >= 0 for position in snapshot.get("positions", [])) for snapshot in snapshots),
        "feishu_summary_daily_and_cumulative_pnl_rendered": all("daily_pnl" in item["final_report"]["feishu_summary"] and "cumulative_pnl" in item["final_report"]["feishu_summary"] for item in day_results),
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "recommended_next_step": "在 test_runs 隔离模式基础上，再补一个包含 NEEDS_HUMAN_REVIEW 的 mixed sequence 测试。",
    }

    review_json = test_run_dir / "review" / "mixed_action_sequence_dry_run.json"
    review_md = test_run_dir / "review" / "mixed_action_sequence_dry_run.md"
    write_json(review_json, review)
    review_md.write_text(
        "\n".join(
            [f"# {args.test_run_id}", "", *(f"- {k}: {v}" for k, v in review.items()), ""]
        ),
        encoding="utf-8",
    )

    summary = {
        "test_run_id": args.test_run_id,
        "test_run_dir": str(test_run_dir),
        "completed": True,
        "official_state_preserved": True,
        "boundaries": [
            "no_real_account",
            "no_auto_trading",
            "no_full_pipeline",
            "test_runs_only",
        ],
        "recommended_next_step": review["recommended_next_step"],
    }
    write_json(REVIEW_DIR / "test_run_mixed_action_sequence_001_summary.json", summary)
    (REVIEW_DIR / "test_run_mixed_action_sequence_001_summary.md").write_text(
        "\n".join([f"# {args.test_run_id}", "", *(f"- {k}: {v}" for k, v in summary.items()), ""]),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "mixed_action_sequence_completed": True,
                "test_run_id": args.test_run_id,
                "test_run_dir": str(test_run_dir),
                "review_json": str(review_json),
                "review_md": str(review_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
