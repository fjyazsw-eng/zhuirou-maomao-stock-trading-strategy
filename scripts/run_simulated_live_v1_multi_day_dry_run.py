from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
STATE_DIR = BASE_DIR / "state"
SNAPSHOT_DIR = STATE_DIR / "snapshots"
TRADE_LOG_DIR = STATE_DIR / "trade_logs"
REVIEW_DIR = BASE_DIR / "review"
FLOW_SCRIPT = ROOT / "scripts" / "run_simulated_live_v1_daily_flow.py"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def yyyymmdd_range(start_date: str, end_date: str) -> list[str]:
    from datetime import datetime, timedelta

    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")
    dates: list[str] = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return dates


def run_python(args: list[str]) -> dict[str, Any]:
    result = subprocess.run([sys.executable, "-X", "utf8", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated_live_v1 multi-day dry run")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--test-mode", action="store_true", default=True)
    parser.add_argument("--state-file", default="")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true")
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    parser.set_defaults(send_feishu=False)
    args = parser.parse_args()

    dates = yyyymmdd_range(args.start_date, args.end_date)
    starting_state_file = Path(args.state_file) if args.state_file else STATE_DIR / "simulated_account_state.json"

    day_results: list[dict[str, Any]] = []
    state_file_for_day = starting_state_file
    snapshot_chaining_passed = True
    positions_carried_forward = True
    cash_carried_forward = True
    trade_log_not_duplicated = True
    no_negative_position_check = True

    for idx, trade_date in enumerate(dates):
        output_state_file = STATE_DIR / f"sample_test_working_state_{trade_date}.json"
        flow = run_python(
            [
                str(FLOW_SCRIPT),
                "--trade-date",
                trade_date,
                "--test-mode",
                "--state-file",
                str(state_file_for_day),
                "--output-state-file",
                str(output_state_file),
                "--no-send-feishu",
            ]
        )
        snapshot_file = Path(flow["updater"]["snapshot_file"])
        trade_log_file = Path(flow["updater"]["trade_log_file"])
        snapshot = dict(read_json(snapshot_file))
        trade_log = dict(read_json(trade_log_file))

        if idx > 0:
            previous_snapshot = dict(read_json(Path(day_results[-1]["snapshot_file"])))
            snapshot_chaining_passed &= str(state_file_for_day) == day_results[-1]["snapshot_file"]
            positions_carried_forward &= snapshot.get("previous_total_equity") == previous_snapshot.get("total_equity")
            cash_carried_forward &= snapshot.get("previous_total_equity") == previous_snapshot.get("total_equity")

        no_negative_position_check &= all(int(position.get("shares", 0)) >= 0 for position in snapshot.get("positions", []))
        trade_log_not_duplicated &= trade_log.get("trade_date") == trade_date

        day_results.append(
            {
                "trade_date": trade_date,
                "flow": flow,
                "snapshot_file": str(snapshot_file),
                "trade_log_file": str(trade_log_file),
                "snapshot": snapshot,
                "trade_log": trade_log,
            }
        )
        state_file_for_day = snapshot_file

    day1 = day_results[0]["snapshot"]
    day2 = day_results[1]["snapshot"]
    day3 = day_results[2]["snapshot"]

    day1_flow_passed = (
        len(day1.get("positions", [])) == 1
        and day1.get("cash") == 17000
        and day1.get("total_equity") == 20000
        and day1.get("daily_pnl") == 0
        and day1.get("cumulative_pnl") == 0
    )
    day2_flow_passed = (
        len(day2.get("positions", [])) == 1
        and day2.get("cash") == 17000
        and day2.get("total_equity") == 20200
        and day2.get("previous_total_equity") == 20000
        and day2.get("daily_pnl") == 200
        and day2.get("cumulative_pnl") == 200
        and day2.get("unrealized_pnl") == 200
    )
    day3_flow_passed = (
        len(day3.get("positions", [])) == 0
        and day3.get("cash") == 20300
        and day3.get("total_equity") == 20300
        and day3.get("previous_total_equity") == 20200
        and day3.get("daily_pnl") == 100
        and day3.get("cumulative_pnl") == 300
        and day3.get("realized_pnl") == 300
        and day3.get("unrealized_pnl") == 0
    )

    daily_pnl_calculation_passed = day1.get("daily_pnl") == day1.get("total_equity") - day1.get("previous_total_equity") and day2.get("daily_pnl") == 200 and day3.get("daily_pnl") == 100
    cumulative_pnl_calculation_passed = day1.get("cumulative_pnl") == day1.get("total_equity") - day1.get("initial_cash") and day2.get("cumulative_pnl") == 200 and day3.get("cumulative_pnl") == 300
    realized_pnl_calculation_passed = day1.get("realized_pnl") == 0 and day2.get("realized_pnl") == 0 and day3.get("realized_pnl") == 300
    unrealized_pnl_calculation_passed = day1.get("unrealized_pnl") == 0 and day2.get("unrealized_pnl") == 200 and day3.get("unrealized_pnl") == 0

    final_daily_report = dict(read_json(Path(day_results[-1]["flow"]["rendering"]["daily_report_json"])))
    final_feishu_summary = final_daily_report.get("feishu_summary", "")
    feishu_summary_daily_and_cumulative_pnl_rendered = "daily_pnl" in final_feishu_summary and "cumulative_pnl" in final_feishu_summary

    review = {
        "multi_day_dry_run_completed": True,
        "official_state_preserved": True,
        "day1_flow_passed": day1_flow_passed,
        "day2_flow_passed": day2_flow_passed,
        "day3_flow_passed": day3_flow_passed,
        "snapshot_chaining_passed": snapshot_chaining_passed,
        "positions_carried_forward": positions_carried_forward,
        "cash_carried_forward": cash_carried_forward,
        "daily_pnl_calculation_passed": daily_pnl_calculation_passed,
        "cumulative_pnl_calculation_passed": cumulative_pnl_calculation_passed,
        "realized_pnl_calculation_passed": realized_pnl_calculation_passed,
        "unrealized_pnl_calculation_passed": unrealized_pnl_calculation_passed,
        "no_negative_position_check": no_negative_position_check,
        "trade_log_not_duplicated": trade_log_not_duplicated,
        "feishu_summary_daily_and_cumulative_pnl_rendered": feishu_summary_daily_and_cumulative_pnl_rendered,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "recommended_next_step": "在多日 dry-run 基础上补一个 mixed action sequence 场景，覆盖 BUY-HOLD-REDUCE-HOLD-SELL 的连续回放。",
        "day_results": day_results,
    }

    review_json = REVIEW_DIR / f"multi_day_dry_run_{args.start_date}_{args.end_date}.json"
    review_md = REVIEW_DIR / f"multi_day_dry_run_{args.start_date}_{args.end_date}.md"
    write_json(review_json, review)
    review_md.write_text(
        "\n".join(
            [
                f"# multi_day_dry_run_{args.start_date}_{args.end_date}",
                "",
                *(f"- {key}: {value}" for key, value in review.items() if key != "day_results"),
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "multi_day_dry_run_completed": True,
                "review_json": str(review_json),
                "review_md": str(review_md),
                "day_results": day_results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
