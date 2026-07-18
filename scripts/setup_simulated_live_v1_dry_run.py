from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
DAILY_DIR = BASE_DIR / "daily"
STATE_DIR = BASE_DIR / "state"
SUMMARY_DIR = BASE_DIR / "summary"
REVIEW_DIR = BASE_DIR / "review"

ACCOUNT_STATE_FILE = STATE_DIR / "simulated_account_state.json"
DAILY_TEMPLATE_FILE = DAILY_DIR / "simulated_live_v1_daily_report_TEMPLATE.md"
FEISHU_TEMPLATE_FILE = REVIEW_DIR / "feishu_daily_message_TEMPLATE.md"
SETUP_JSON_FILE = REVIEW_DIR / "simulated_live_v1_dry_run_setup_20260706.json"
SETUP_MD_FILE = REVIEW_DIR / "simulated_live_v1_dry_run_setup_20260706.md"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_directories() -> list[str]:
    dirs = [BASE_DIR, DAILY_DIR, STATE_DIR, SUMMARY_DIR, REVIEW_DIR]
    for directory in dirs:
        directory.mkdir(parents=True, exist_ok=True)
    return [str(directory) for directory in dirs]


def build_account_state(now_text: str) -> dict[str, Any]:
    return {
        "account_id": "sim_v1_local_only",
        "currency": "CNY",
        "initial_cash": 20000,
        "cash": 20000,
        "total_equity": 20000,
        "positions": [],
        "max_position_per_stock": 0.20,
        "max_total_position": 0.60,
        "max_new_buy_per_day": 1,
        "max_total_trades_per_day": 2,
        "lot_size": 100,
        "trade_count_today": 0,
        "new_buy_count_today": 0,
        "unrealized_pnl": 0,
        "realized_pnl": 0,
        "daily_pnl": 0,
        "daily_pnl_ratio": 0,
        "account_risk_flags": [],
        "last_update": now_text,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "news_module_enabled": False,
    }


def write_daily_template() -> None:
    content = """# simulated_live_v1_daily_report

## 今日日期
- trade_date:

## 今日市场状态
- 市场状态:
- 指数环境:
- 风格观察:

## 候选股池
- 候选列表:

## 原模型建议 original_model_action
- original_model_action:

## AI审核建议 ai_review_shadow_action
- ai_review_shadow_action:

## 最终建议 final_user_action
- final_user_action:

## 操作计划
- 今日操作计划:

## 决策思路
- 核心决策思路:

## 当前模拟账户状态
- total_equity:
- cash:
- daily_trade_count:
- new_buy_count_today:

## 当前模拟持仓
- positions:

## 当日模拟盈亏
- daily_pnl:
- daily_pnl_ratio:
- realized_pnl:
- unrealized_pnl:

## 风险提示
- 风险提示:

## 人工复核项
- NEEDS_HUMAN_REVIEW 项:

## 明日观察条件
- 明日观察条件:

## 飞书摘要
- feishu_message_summary:
"""
    DAILY_TEMPLATE_FILE.write_text(content, encoding="utf-8")


def write_feishu_template() -> None:
    content = """【模拟实盘日报】
日期：
模拟账户总资产：
当日盈亏：
当日盈亏比例：
当前现金：
当前持仓：
今日操作计划：
核心判断思路：
AI审核意见：
风险提示：
明日观察条件：
备注：本报告仅为模拟记录，不代表真实交易，不会自动下单。
"""
    FEISHU_TEMPLATE_FILE.write_text(content, encoding="utf-8")


def build_setup_report(now_text: str) -> dict[str, Any]:
    return {
        "dry_run_setup_completed": True,
        "initial_cash": 20000,
        "risk_config": {
            "max_position_per_stock": 0.20,
            "max_total_position": 0.60,
            "max_new_buy_per_day": 1,
            "max_total_trades_per_day": 2,
            "lot_size": 100,
            "lot_value_exceeds_position_limit_downgrade_to_observe": True,
        },
        "account_state_file": str(ACCOUNT_STATE_FILE),
        "daily_report_template_file": str(DAILY_TEMPLATE_FILE),
        "feishu_template_file": str(FEISHU_TEMPLATE_FILE),
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "news_module_enabled": False,
        "full_pipeline_enabled": False,
        "can_run_daily_simulated_report_next": True,
        "recommended_next_step": "build first daily simulated report shell using local simulated_account_state only",
        "generated_at": now_text,
    }


def write_setup_markdown(report: dict[str, Any]) -> None:
    risk = report["risk_config"]
    content = f"""# simulated_live_v1_dry_run_setup_20260706

- dry_run_setup_completed: {report['dry_run_setup_completed']}
- initial_cash: {report['initial_cash']}
- risk_config:
  - max_position_per_stock: {risk['max_position_per_stock']}
  - max_total_position: {risk['max_total_position']}
  - max_new_buy_per_day: {risk['max_new_buy_per_day']}
  - max_total_trades_per_day: {risk['max_total_trades_per_day']}
  - lot_size: {risk['lot_size']}
  - lot_value_exceeds_position_limit_downgrade_to_observe: {risk['lot_value_exceeds_position_limit_downgrade_to_observe']}
- account_state_file: {report['account_state_file']}
- daily_report_template_file: {report['daily_report_template_file']}
- feishu_template_file: {report['feishu_template_file']}
- real_account_connected: {report['real_account_connected']}
- auto_trading_enabled: {report['auto_trading_enabled']}
- news_module_enabled: {report['news_module_enabled']}
- full_pipeline_enabled: {report['full_pipeline_enabled']}
- can_run_daily_simulated_report_next: {report['can_run_daily_simulated_report_next']}
- recommended_next_step: {report['recommended_next_step']}
- generated_at: {report['generated_at']}
"""
    SETUP_MD_FILE.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup simulated live v1 dry run shell")
    parser.add_argument("--reset", action="store_true", help="Reset simulated account state file")
    args = parser.parse_args()

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    directories = ensure_directories()

    state_created = False
    if args.reset or not ACCOUNT_STATE_FILE.exists():
        write_json(ACCOUNT_STATE_FILE, build_account_state(now_text))
        state_created = True

    write_daily_template()
    write_feishu_template()

    report = build_setup_report(now_text)
    write_json(SETUP_JSON_FILE, report)
    write_setup_markdown(report)

    print(
        json.dumps(
            {
                "dry_run_setup_completed": True,
                "directories": directories,
                "account_state_file": str(ACCOUNT_STATE_FILE),
                "account_state_created_or_reset": state_created,
                "daily_report_template_file": str(DAILY_TEMPLATE_FILE),
                "feishu_template_file": str(FEISHU_TEMPLATE_FILE),
                "setup_report_json": str(SETUP_JSON_FILE),
                "setup_report_md": str(SETUP_MD_FILE),
                "can_run_daily_simulated_report_next": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
