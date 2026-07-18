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
DAILY_DIR = BASE_DIR / "daily"
INPUT_DIR = BASE_DIR / "input"
MARKET_DATA_DIR = INPUT_DIR / "market_data"
CANDIDATE_POOL_DIR = INPUT_DIR / "candidate_pool"
REVIEW_DIR = BASE_DIR / "review"

UPDATE_SCRIPT = ROOT / "scripts" / "update_simulated_account_state.py"
BUILD_SCRIPT = ROOT / "scripts" / "build_simulated_live_v1_daily_report.py"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_python(args: list[str]) -> dict[str, Any]:
    result = subprocess.run([sys.executable, "-X", "utf8", *args], cwd=ROOT, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one simulated_live_v1 daily flow")
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--test-mode", action="store_true", default=True)
    parser.add_argument("--state-file", default="")
    parser.add_argument("--output-state-file", default="")
    parser.add_argument("--send-feishu", dest="send_feishu", action="store_true")
    parser.add_argument("--no-send-feishu", dest="send_feishu", action="store_false")
    parser.set_defaults(send_feishu=False)
    args = parser.parse_args()

    trade_date = args.trade_date
    state_file = Path(args.state_file) if args.state_file else STATE_DIR / "simulated_account_state.json"
    output_state_file = Path(args.output_state_file) if args.output_state_file else state_file

    market_data_file = MARKET_DATA_DIR / f"market_data_{trade_date}.json"
    candidate_pool_file = CANDIDATE_POOL_DIR / f"candidate_pool_{trade_date}.json"
    daily_report_file = DAILY_DIR / f"simulated_live_v1_daily_report_{trade_date}.json"
    snapshot_file = SNAPSHOT_DIR / f"simulated_account_state_{trade_date}.json"
    trade_log_file = TRADE_LOG_DIR / f"simulated_trade_log_{trade_date}.json"
    flow_report_json = REVIEW_DIR / f"daily_flow_review_{trade_date}.json"
    flow_report_md = REVIEW_DIR / f"daily_flow_review_{trade_date}.md"

    market_data_loaded = market_data_file.exists()
    candidate_pool_loaded = candidate_pool_file.exists()
    daily_report_loaded_or_generated = daily_report_file.exists()

    updater = run_python(
        [
            str(UPDATE_SCRIPT),
            "--trade-date",
            trade_date,
            "--dry-run",
            "--state-file",
            str(state_file),
            "--output-state-file",
            str(output_state_file),
        ]
    )

    render_state_file = snapshot_file if snapshot_file.exists() else output_state_file

    rendering = run_python(
        [
            str(BUILD_SCRIPT),
            "--trade-date",
            trade_date,
            "--state-file",
            str(render_state_file),
            "--trade-log-file",
            str(trade_log_file),
            "--test-mode",
        ]
    )

    snapshot = dict(read_json(snapshot_file))
    final_daily_report = dict(read_json(daily_report_file))
    feishu_message_file = Path(rendering["feishu_message_md"])

    flow_report = {
        "flow_completed": True,
        "trade_date": trade_date,
        "test_mode": args.test_mode,
        "market_data_loaded": market_data_loaded,
        "candidate_pool_loaded": candidate_pool_loaded,
        "daily_report_loaded_or_generated": daily_report_loaded_or_generated,
        "account_updater_ran": True,
        "action_rendering_ran": True,
        "final_daily_report_generated": Path(rendering["daily_report_json"]).exists(),
        "feishu_summary_generated": feishu_message_file.exists(),
        "feishu_sent": False,
        "state_file_used": str(state_file),
        "output_state_file": str(output_state_file),
        "snapshot_file": str(snapshot_file),
        "trade_log_file": str(trade_log_file),
        "positions_count": len(snapshot.get("positions", [])),
        "final_user_action": final_daily_report.get("final_user_action"),
        "action_executed": final_daily_report.get("action_executed"),
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "recommended_next_step": "connect this daily flow to a reusable sample or manual input preparation step for repeated dry runs",
    }
    write_json(flow_report_json, flow_report)
    flow_report_md.write_text(
        "\n".join(
            [f"# daily_flow_review_{trade_date}", "", *(f"- {k}: {v}" for k, v in flow_report.items()), ""]
        ),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "flow_completed": True,
                "trade_date": trade_date,
                "updater": updater,
                "rendering": rendering,
                "flow_report_json": str(flow_report_json),
                "flow_report_md": str(flow_report_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
