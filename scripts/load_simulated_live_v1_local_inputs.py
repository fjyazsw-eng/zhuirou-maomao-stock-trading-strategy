from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
INPUT_DIR = BASE_DIR / "input"
MARKET_DATA_DIR = INPUT_DIR / "market_data"
CANDIDATE_POOL_DIR = INPUT_DIR / "candidate_pool"
REVIEW_DIR = BASE_DIR / "review"

MARKET_DATA_TEMPLATE_FILE = MARKET_DATA_DIR / "market_data_TEMPLATE.json"
CANDIDATE_POOL_TEMPLATE_FILE = CANDIDATE_POOL_DIR / "candidate_pool_TEMPLATE.json"
REPORT_JSON_FILE = REVIEW_DIR / "local_market_data_input_stub_20260706.json"
REPORT_MD_FILE = REVIEW_DIR / "local_market_data_input_stub_20260706.md"


def write_json(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_directories() -> list[str]:
    dirs = [INPUT_DIR, MARKET_DATA_DIR, CANDIDATE_POOL_DIR, REVIEW_DIR]
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
    return [str(directory) for directory in dirs]


def market_data_template() -> dict[str, Any]:
    return {
        "trade_date": "YYYYMMDD",
        "data_source": "local_stub",
        "market_snapshot": {
            "sh_index": None,
            "sz_index": None,
            "cyb_index": None,
            "kcb50_index": None,
            "up_count": None,
            "down_count": None,
            "total_amount": None,
            "market_state": "UNKNOWN",
        },
        "index_context": {
            "short_term_trend": "UNKNOWN",
            "risk_appetite": "UNKNOWN",
            "volume_state": "UNKNOWN",
        },
        "target_symbols_ohlc": [],
        "notes": "template only; no real market data",
    }


def candidate_pool_template() -> list[dict[str, Any]]:
    return [
        {
            "ts_code": "",
            "name": "",
            "candidate_source": "manual_input",
            "candidate_action_hint": "OBSERVE",
            "reason": "",
            "sector": "",
            "watch_price": None,
            "stop_loss_price": None,
            "max_position_ratio": 0.2,
            "notes": "template only",
        }
    ]


def ensure_templates() -> tuple[bool, bool]:
    market_created = False
    candidate_created = False
    if not MARKET_DATA_TEMPLATE_FILE.exists():
        write_json(MARKET_DATA_TEMPLATE_FILE, market_data_template())
        market_created = True
    if not CANDIDATE_POOL_TEMPLATE_FILE.exists():
        write_json(CANDIDATE_POOL_TEMPLATE_FILE, candidate_pool_template())
        candidate_created = True
    return market_created, candidate_created


def load_market_data(trade_date: str) -> tuple[dict[str, Any], bool]:
    dated_file = MARKET_DATA_DIR / f"market_data_{trade_date}.json"
    if dated_file.exists():
        return dict(read_json(dated_file)), False
    return dict(read_json(MARKET_DATA_TEMPLATE_FILE)), True


def load_candidate_pool(trade_date: str) -> tuple[list[dict[str, Any]], bool]:
    dated_file = CANDIDATE_POOL_DIR / f"candidate_pool_{trade_date}.json"
    if dated_file.exists():
        return list(read_json(dated_file)), False
    return list(read_json(CANDIDATE_POOL_TEMPLATE_FILE)), True


def build_report(
    *,
    trade_date: str,
    input_directories_created: bool,
    market_data_is_template: bool,
    candidate_pool_is_template: bool,
) -> dict[str, Any]:
    return {
        "local_input_stub_created": True,
        "input_directories_created": input_directories_created,
        "market_data_template_file": str(MARKET_DATA_TEMPLATE_FILE),
        "candidate_pool_template_file": str(CANDIDATE_POOL_TEMPLATE_FILE),
        "market_data_loaded": True,
        "market_data_is_template": market_data_is_template,
        "candidate_pool_loaded": True,
        "candidate_pool_is_template": candidate_pool_is_template,
        "real_market_data_connected": False,
        "tushare_connected": False,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "can_build_daily_report_with_local_input": True,
        "recommended_next_step": "connect build_simulated_live_v1_daily_report.py to dated local input files or create first manual market_data_YYYYMMDD.json sample",
        "trade_date_checked": trade_date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_report_markdown(path: Path, report: dict[str, Any]) -> None:
    content = f"""# local_market_data_input_stub_20260706

- local_input_stub_created: {report['local_input_stub_created']}
- input_directories_created: {report['input_directories_created']}
- market_data_template_file: {report['market_data_template_file']}
- candidate_pool_template_file: {report['candidate_pool_template_file']}
- market_data_loaded: {report['market_data_loaded']}
- market_data_is_template: {report['market_data_is_template']}
- candidate_pool_loaded: {report['candidate_pool_loaded']}
- candidate_pool_is_template: {report['candidate_pool_is_template']}
- real_market_data_connected: {report['real_market_data_connected']}
- tushare_connected: {report['tushare_connected']}
- real_account_connected: {report['real_account_connected']}
- auto_trading_enabled: {report['auto_trading_enabled']}
- full_pipeline_enabled: {report['full_pipeline_enabled']}
- news_module_enabled: {report['news_module_enabled']}
- can_build_daily_report_with_local_input: {report['can_build_daily_report_with_local_input']}
- recommended_next_step: {report['recommended_next_step']}
- trade_date_checked: {report['trade_date_checked']}
- generated_at: {report['generated_at']}
"""
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Load simulated live v1 local inputs")
    parser.add_argument("--trade-date", default=datetime.now().strftime("%Y%m%d"))
    args = parser.parse_args()

    directories_before = [INPUT_DIR.exists(), MARKET_DATA_DIR.exists(), CANDIDATE_POOL_DIR.exists()]
    ensure_directories()
    input_directories_created = not all(directories_before)
    ensure_templates()

    _, market_data_is_template = load_market_data(args.trade_date)
    _, candidate_pool_is_template = load_candidate_pool(args.trade_date)

    report = build_report(
        trade_date=args.trade_date,
        input_directories_created=input_directories_created,
        market_data_is_template=market_data_is_template,
        candidate_pool_is_template=candidate_pool_is_template,
    )
    write_json(REPORT_JSON_FILE, report)
    write_report_markdown(REPORT_MD_FILE, report)

    print(
        json.dumps(
            {
                "local_input_stub_created": True,
                "market_data_template_file": str(MARKET_DATA_TEMPLATE_FILE),
                "candidate_pool_template_file": str(CANDIDATE_POOL_TEMPLATE_FILE),
                "market_data_is_template": market_data_is_template,
                "candidate_pool_is_template": candidate_pool_is_template,
                "can_build_daily_report_with_local_input": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
