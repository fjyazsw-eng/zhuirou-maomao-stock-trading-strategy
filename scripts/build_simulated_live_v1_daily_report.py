from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scoring_system.output_formatter import compact_table, compact_trade_advice


ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = ROOT / "reports" / "simulated_live_v1"
DAILY_DIR = BASE_DIR / "daily"
STATE_DIR = BASE_DIR / "state"
SNAPSHOT_DIR = STATE_DIR / "snapshots"
TRADE_LOG_DIR = STATE_DIR / "trade_logs"
INPUT_DIR = BASE_DIR / "input"
MARKET_DATA_DIR = INPUT_DIR / "market_data"
CANDIDATE_POOL_DIR = INPUT_DIR / "candidate_pool"
REVIEW_DIR = BASE_DIR / "review"

ACCOUNT_STATE_FILE = STATE_DIR / "simulated_account_state.json"
DAILY_TEMPLATE_FILE = DAILY_DIR / "simulated_live_v1_daily_report_TEMPLATE.md"
FEISHU_TEMPLATE_FILE = REVIEW_DIR / "feishu_daily_message_TEMPLATE.md"
MARKET_DATA_TEMPLATE_FILE = MARKET_DATA_DIR / "market_data_TEMPLATE.json"
CANDIDATE_POOL_TEMPLATE_FILE = CANDIDATE_POOL_DIR / "candidate_pool_TEMPLATE.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_dirs() -> None:
    for directory in [DAILY_DIR, REVIEW_DIR, MARKET_DATA_DIR, CANDIDATE_POOL_DIR, SNAPSHOT_DIR, TRADE_LOG_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def ensure_sample_inputs(trade_date: str) -> None:
    ensure_dirs()
    market_data_file = MARKET_DATA_DIR / f"market_data_{trade_date}.json"
    candidate_pool_file = CANDIDATE_POOL_DIR / f"candidate_pool_{trade_date}.json"
    manual_candidate_pool_file = CANDIDATE_POOL_DIR / "candidate_pool_MANUAL.json"

    if not market_data_file.exists():
        write_json(
            market_data_file,
            {
                "trade_date": trade_date,
                "data_source": "local_sample",
                "is_sample_data": True,
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
            },
        )

    if not candidate_pool_file.exists() and not manual_candidate_pool_file.exists():
        write_json(
            candidate_pool_file,
            [
                {
                    "ts_code": "",
                    "name": "",
                    "candidate_source": "local_sample",
                    "candidate_action_hint": "OBSERVE",
                    "reason": "template only",
                    "sector": "",
                    "watch_price": None,
                    "stop_loss_price": None,
                    "max_position_ratio": 0.2,
                    "notes": "sample only; not investment advice",
                }
            ],
        )


def load_market_data(trade_date: str) -> tuple[dict[str, Any], Path, bool, bool]:
    dated_file = MARKET_DATA_DIR / f"market_data_{trade_date}.json"
    if dated_file.exists():
        payload = dict(read_json(dated_file))
        return payload, dated_file, False, bool(payload.get("is_sample_data", False))
    payload = dict(read_json(MARKET_DATA_TEMPLATE_FILE))
    return payload, MARKET_DATA_TEMPLATE_FILE, True, bool(payload.get("is_sample_data", False))


def load_candidate_pool(trade_date: str) -> tuple[list[dict[str, Any]], Path, bool, bool]:
    dated_file = CANDIDATE_POOL_DIR / f"candidate_pool_{trade_date}.json"
    manual_file = CANDIDATE_POOL_DIR / "candidate_pool_MANUAL.json"
    if dated_file.exists():
        payload = list(read_json(dated_file))
        is_sample = any(item.get("candidate_source") == "local_sample" for item in payload)
        return payload, dated_file, False, is_sample
    if manual_file.exists():
        payload = list(read_json(manual_file))
        is_sample = any(item.get("candidate_source") == "local_sample" for item in payload)
        return payload, manual_file, False, is_sample
    payload = list(read_json(CANDIDATE_POOL_TEMPLATE_FILE))
    is_sample = any(item.get("candidate_source") == "local_sample" for item in payload)
    return payload, CANDIDATE_POOL_TEMPLATE_FILE, True, is_sample


def load_account_state(trade_date: str, state_file_arg: str | None) -> tuple[dict[str, Any], Path]:
    if state_file_arg:
        path = Path(state_file_arg)
        return dict(read_json(path)), path
    snapshot_file = SNAPSHOT_DIR / f"simulated_account_state_{trade_date}.json"
    if snapshot_file.exists():
        return dict(read_json(snapshot_file)), snapshot_file
    return dict(read_json(ACCOUNT_STATE_FILE)), ACCOUNT_STATE_FILE


def load_daily_decision(trade_date: str) -> tuple[dict[str, Any], Path | None]:
    path = DAILY_DIR / f"simulated_live_v1_daily_report_{trade_date}.json"
    if path.exists():
        return dict(read_json(path)), path
    return {}, None


def load_trade_log(trade_date: str, trade_log_arg: str | None) -> tuple[dict[str, Any], Path | None]:
    if trade_log_arg:
        path = Path(trade_log_arg)
        if path.exists():
            return dict(read_json(path)), path
        return {}, path
    path = TRADE_LOG_DIR / f"simulated_trade_log_{trade_date}.json"
    if path.exists():
        return dict(read_json(path)), path
    return {}, None


def safe_float(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def compute_account_summary(account_state: dict[str, Any]) -> dict[str, Any]:
    total_equity = safe_float(account_state.get("total_equity"))
    cash = safe_float(account_state.get("cash"))
    market_value = round(sum(safe_float(position.get("market_value")) for position in account_state.get("positions", [])), 4)
    total_position_ratio = 0.0 if total_equity <= 0 else round(market_value / total_equity, 6)
    previous_total_equity = safe_float(account_state.get("previous_total_equity", account_state.get("initial_cash")))
    return {
        "initial_cash": safe_float(account_state.get("initial_cash")),
        "previous_total_equity": previous_total_equity,
        "total_equity": total_equity,
        "cash": cash,
        "market_value": market_value,
        "total_position_ratio": total_position_ratio,
        "daily_pnl": safe_float(account_state.get("daily_pnl")),
        "daily_pnl_ratio": safe_float(account_state.get("daily_pnl_ratio")),
        "cumulative_pnl": safe_float(account_state.get("cumulative_pnl")),
        "cumulative_pnl_ratio": safe_float(account_state.get("cumulative_pnl_ratio")),
        "realized_pnl": safe_float(account_state.get("realized_pnl")),
        "unrealized_pnl": safe_float(account_state.get("unrealized_pnl")),
    }


def build_positions_view(account_state: dict[str, Any], summary: dict[str, Any]) -> list[dict[str, Any]]:
    total_equity = summary["total_equity"]
    result = []
    for position in account_state.get("positions", []):
        market_value = safe_float(position.get("market_value"))
        result.append(
            {
                "ts_code": position.get("ts_code", ""),
                "name": position.get("name", ""),
                "shares": int(position.get("shares", 0)),
                "cost_basis": safe_float(position.get("cost_basis")),
                "mark_price": safe_float(position.get("mark_price")),
                "market_value": market_value,
                "unrealized_pnl": safe_float(position.get("unrealized_pnl")),
                "position_ratio": 0.0 if total_equity <= 0 else round(market_value / total_equity, 6),
                "holding_status": "ACTIVE" if int(position.get("shares", 0)) > 0 else "EMPTY",
            }
        )
    return result


def build_action_summary(daily_decision: dict[str, Any], trade_log: dict[str, Any]) -> dict[str, Any]:
    final_user_action = daily_decision.get("final_user_action", "OBSERVE")
    action_requested = trade_log.get("action_requested", final_user_action)
    action_executed = trade_log.get("action_executed", final_user_action)
    shares = int(trade_log.get("shares", 0) or 0)
    human_review_reason = trade_log.get("human_review_reason", [])
    if isinstance(human_review_reason, str):
        human_review_reason = [human_review_reason]
    return {
        "final_user_action": final_user_action,
        "action_requested": action_requested,
        "action_executed": action_executed,
        "simulated_trade_occurred": action_executed in {"BUY", "REDUCE", "SELL"} and shares > 0,
        "block_reason": trade_log.get("block_reason", ""),
        "human_review_reason": human_review_reason,
        "price": trade_log.get("price"),
        "shares": shares,
    }


def build_risk_status(account_state: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "max_position_per_stock": account_state.get("max_position_per_stock"),
        "max_total_position": account_state.get("max_total_position"),
        "max_new_buy_per_day": account_state.get("max_new_buy_per_day"),
        "max_total_trades_per_day": account_state.get("max_total_trades_per_day"),
        "current_position_usage": summary["total_position_ratio"],
        "trade_count_today": account_state.get("trade_count_today", 0),
        "new_buy_count_today": account_state.get("new_buy_count_today", 0),
        "account_risk_flags": account_state.get("account_risk_flags", []),
    }


def build_next_day_watch_conditions(positions_view: list[dict[str, Any]], human_review_items: list[str]) -> list[str]:
    if positions_view:
        conditions = [
            "继续观察持仓价格变化。",
            "关注是否触发 HOLD / REDUCE / SELL 条件。",
        ]
        if human_review_items:
            conditions.append("存在人工复核项，明日优先人工复核。")
        return conditions
    return [
        "等待候选股池与真实行情输入。",
        "不根据 sample 数据做买入判断。",
    ]


def build_feishu_summary(
    trade_date: str,
    summary: dict[str, Any],
    positions_view: list[dict[str, Any]],
    action_summary: dict[str, Any],
    human_review_items: list[str],
) -> str:
    review_preview = "；".join(human_review_items[:2]) if human_review_items else "暂无人工复核项"
    return compact_table(
        f"模拟日报 {trade_date}",
        [
            ("阶段", "观察 / 只读"),
            ("空仓建议", "观察"),
            ("持仓建议", action_summary["action_executed"]),
            ("仓位建议", f"{round(summary['total_position_ratio'] * 100, 1)}%"),
            ("失效条件", "行情缺失或人工复核未通过"),
            ("下一步", review_preview),
        ],
    )


def build_feishu_message(
    trade_date: str,
    summary: dict[str, Any],
    positions_view: list[dict[str, Any]],
    action_summary: dict[str, Any],
    human_review_items: list[str],
    next_day_watch_conditions: list[str],
) -> str:
    positions_text = "无模拟持仓" if not positions_view else "；".join(
        f"{item['ts_code']} {item['shares']}股 市值{item['market_value']}" for item in positions_view
    )
    review_text = "暂无人工复核项" if not human_review_items else "；".join(human_review_items[:3])
    overview = compact_table(
        f"模拟实盘日报 {trade_date}",
        [
            ("阶段", "观察 / 只读"),
            ("买点等级", "D"),
            ("空仓操作", "观察"),
            ("持仓操作", action_summary["action_executed"]),
            ("建议仓位", f"{round(summary['total_position_ratio'] * 100, 1)}%"),
            ("止损/失效", "行情缺失或人工复核未通过"),
            ("下一步看点", next_day_watch_conditions[0] if next_day_watch_conditions else "等待下一交易日"),
        ],
    )
    advice = compact_trade_advice(
        empty_action="观察",
        holding_action=action_summary["action_executed"],
        add_action="不加",
        sell_action="等人工复核后处理",
        buy_condition="候选股和真实行情同时齐备。",
        reduce_condition="人工复核提示转弱或风控触发。",
        stop_condition="失效条件出现即不再执行试错。",
        max_position=f"{round(summary['total_position_ratio'] * 100, 1)}%",
        final_line="当前只做只读和复核，不做自动交易。",
    )
    return "\n\n".join(
        [
            overview,
            f"一句话：当前持仓 {positions_text}；人工复核：{review_text}。",
            advice,
        ]
    )


def render_positions_markdown(positions_view: list[dict[str, Any]]) -> str:
    if not positions_view:
        return "- 当前无模拟持仓。"
    return "\n".join(
        [
            (
                f"- {item['ts_code']} / {item['name']} / shares={item['shares']} / "
                f"cost_basis={item['cost_basis']} / mark_price={item['mark_price']} / "
                f"market_value={item['market_value']} / unrealized_pnl={item['unrealized_pnl']} / "
                f"position_ratio={item['position_ratio']} / holding_status={item['holding_status']}"
            )
            for item in positions_view
        ]
    )


def render_candidate_quotes_markdown(market_data: dict[str, Any]) -> str:
    quotes = market_data.get("target_symbols_ohlc", [])
    if not quotes:
        return "- 暂无候选股个股行情；如候选池为空或 Tushare 未返回数据，会在 data_quality.missing_symbols 中体现。"
    lines = [
        "| ts_code | name | open | high | low | close | pre_close | pct_chg | amount |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in quotes:
        lines.append(
            "| {ts_code} | {name} | {open} | {high} | {low} | {close} | {pre_close} | {pct_chg} | {amount} |".format(
                ts_code=item.get("ts_code", ""),
                name=item.get("name", ""),
                open=item.get("open", ""),
                high=item.get("high", ""),
                low=item.get("low", ""),
                close=item.get("close", ""),
                pre_close=item.get("pre_close", ""),
                pct_chg=item.get("pct_chg", ""),
                amount=item.get("amount", ""),
            )
        )
    return "\n".join(lines)


def render_section(title: str, lines: list[str]) -> str:
    return f"## {title}\n" + "\n".join(lines)


def write_reading_report(trade_date: str, report: dict[str, Any]) -> tuple[Path, Path]:
    report_json = REVIEW_DIR / f"daily_report_local_input_reading_{trade_date}.json"
    report_md = REVIEW_DIR / f"daily_report_local_input_reading_{trade_date}.md"
    write_json(report_json, report)
    report_md.write_text(
        "\n".join(
            [f"# daily_report_local_input_reading_{trade_date}", "", *(f"- {k}: {v}" for k, v in report.items()), ""]
        ),
        encoding="utf-8",
    )
    return report_json, report_md


def main() -> int:
    parser = argparse.ArgumentParser(description="Build simulated live v1 daily report with local input")
    parser.add_argument("--trade-date", default=datetime.now().strftime("%Y%m%d"))
    parser.add_argument("--state-file", default="")
    parser.add_argument("--trade-log-file", default="")
    parser.add_argument("--test-mode", action="store_true")
    args = parser.parse_args()

    trade_date = args.trade_date
    ensure_sample_inputs(trade_date)
    _ = DAILY_TEMPLATE_FILE.read_text(encoding="utf-8")
    _ = FEISHU_TEMPLATE_FILE.read_text(encoding="utf-8")

    account_state, state_file_used = load_account_state(trade_date, args.state_file or None)
    daily_decision, daily_decision_file_used = load_daily_decision(trade_date)
    trade_log, trade_log_file_used = load_trade_log(trade_date, args.trade_log_file or None)
    market_data, market_data_file_used, market_data_is_template, market_data_is_sample = load_market_data(trade_date)
    candidate_pool, candidate_pool_file_used, candidate_pool_is_template, candidate_pool_is_sample = load_candidate_pool(trade_date)

    human_review_items = list(account_state.get("human_review_items", []))
    summary = compute_account_summary(account_state)
    positions_view = build_positions_view(account_state, summary)
    action_summary = build_action_summary(daily_decision, trade_log)
    risk_status = build_risk_status(account_state, summary)
    next_day_watch_conditions = build_next_day_watch_conditions(positions_view, human_review_items)
    feishu_summary = build_feishu_summary(trade_date, summary, positions_view, action_summary, human_review_items)

    daily_report_md = DAILY_DIR / f"simulated_live_v1_daily_report_{trade_date}.md"
    daily_report_json = DAILY_DIR / f"simulated_live_v1_daily_report_{trade_date}.json"
    feishu_message_md = REVIEW_DIR / f"feishu_daily_message_{trade_date}.md"

    is_real_market_data = bool(market_data.get("is_real_market_data", False))
    readonly_render_only = True
    trade_decision_generated = False
    market_state_line = (
        "本报告只读展示真实行情，不生成买卖建议。"
        if is_real_market_data
        else ("本报告使用本地样例数据，不代表真实市场判断。" if market_data_is_sample else "市场数据未接入，本报告为日报外壳测试。")
    )
    candidate_line = (
        "候选股池来自 manual_watchlist，仅用于只读行情展示，不代表买入建议。"
        if candidate_pool_file_used.name == "candidate_pool_MANUAL.json"
        else ("候选股池使用本地样例数据，不代表真实推荐。" if candidate_pool_is_sample else "候选股池为占位模板，未进行全市场自动选股。")
    )

    daily_report_md.write_text(
        "\n\n".join(
            [
                f"# simulated_live_v1_daily_report_{trade_date}",
                render_section("今日日期", [f"- {trade_date}"]),
                render_section(
                    "今日市场状态",
                    [
                        f"- {market_state_line}",
                        f"- market_data_is_template: {market_data_is_template}",
                        f"- market_data_is_sample: {market_data_is_sample}",
                        f"- data_source: {market_data.get('data_source')}",
                        f"- is_real_market_data: {is_real_market_data}",
                        f"- readonly_render_only: {readonly_render_only}",
                        f"- trade_decision_generated: {trade_decision_generated}",
                        f"- market_state: {market_data.get('market_snapshot', {}).get('market_state', 'UNKNOWN')}",
                        f"- data_quality: {json.dumps(market_data.get('data_quality', {}), ensure_ascii=False)}",
                    ],
                ),
                render_section(
                    "候选股池",
                    [
                        f"- {candidate_line}",
                        f"- candidate_pool_is_template: {candidate_pool_is_template}",
                        f"- candidate_pool_is_sample: {candidate_pool_is_sample}",
                        f"- candidate_pool_file_used: {candidate_pool_file_used}",
                        f"- candidate_pool: {json.dumps(candidate_pool, ensure_ascii=False)}",
                    ],
                ),
                "## 候选股只读行情\n" + render_candidate_quotes_markdown(market_data),
                render_section(
                    "模拟账户总览",
                    [
                        f"- initial_cash: {summary['initial_cash']}",
                        f"- previous_total_equity: {summary['previous_total_equity']}",
                        f"- total_equity: {summary['total_equity']}",
                        f"- cash: {summary['cash']}",
                        f"- market_value: {summary['market_value']}",
                        f"- total_position_ratio: {summary['total_position_ratio']}",
                        f"- daily_pnl: {summary['daily_pnl']}",
                        f"- daily_pnl_ratio: {summary['daily_pnl_ratio']}",
                        f"- cumulative_pnl: {summary['cumulative_pnl']}",
                        f"- cumulative_pnl_ratio: {summary['cumulative_pnl_ratio']}",
                        f"- realized_pnl: {summary['realized_pnl']}",
                        f"- unrealized_pnl: {summary['unrealized_pnl']}",
                    ],
                ),
                "## 当前模拟持仓\n" + render_positions_markdown(positions_view),
                render_section(
                    "今日动作汇总",
                    [
                        f"- final_user_action: {action_summary['final_user_action']}",
                        f"- action_requested: {action_summary['action_requested']}",
                        f"- action_executed: {action_summary['action_executed']}",
                        f"- 是否发生模拟交易: {action_summary['simulated_trade_occurred']}",
                        f"- block_reason: {action_summary['block_reason']}",
                        f"- human_review_reason: {action_summary['human_review_reason']}",
                    ],
                ),
                render_section(
                    "人工复核项",
                    ["- 暂无人工复核项"] if not human_review_items else [f"- {item}" for item in human_review_items],
                ),
                render_section(
                    "风控状态",
                    [
                        f"- max_position_per_stock: {risk_status['max_position_per_stock']}",
                        f"- max_total_position: {risk_status['max_total_position']}",
                        f"- max_new_buy_per_day: {risk_status['max_new_buy_per_day']}",
                        f"- max_total_trades_per_day: {risk_status['max_total_trades_per_day']}",
                        f"- current_position_usage: {risk_status['current_position_usage']}",
                        f"- trade_count_today: {risk_status['trade_count_today']}",
                        f"- new_buy_count_today: {risk_status['new_buy_count_today']}",
                        f"- account_risk_flags: {risk_status['account_risk_flags']}",
                    ],
                ),
                render_section("明日观察条件", [f"- {item}" for item in next_day_watch_conditions]),
                render_section("飞书摘要", [f"- {feishu_summary}"]),
            ]
        ),
        encoding="utf-8",
    )

    payload = {
        "trade_date": trade_date,
        "state_file_used": str(state_file_used),
        "daily_decision_file_used": str(daily_decision_file_used) if daily_decision_file_used else "",
        "trade_log_file_used": str(trade_log_file_used) if trade_log_file_used else "",
        "market_data_file_used": str(market_data_file_used),
        "candidate_pool_file_used": str(candidate_pool_file_used),
        "market_data_is_template": market_data_is_template,
        "market_data_is_sample": market_data_is_sample,
        "candidate_pool_is_template": candidate_pool_is_template,
        "candidate_pool_is_sample": candidate_pool_is_sample,
        "readonly_render_only": readonly_render_only,
        "trade_decision_generated": trade_decision_generated,
        "is_real_market_data": is_real_market_data,
        "target_symbols_ohlc": market_data.get("target_symbols_ohlc", []),
        "candidate_quotes_rendered": bool(market_data.get("target_symbols_ohlc", [])),
        "data_quality": market_data.get("data_quality", {}),
        "test_mode": args.test_mode,
        "original_model_action": daily_decision.get("original_model_action", "OBSERVE"),
        "ai_review_shadow_action": daily_decision.get("ai_review_shadow_action", "OBSERVE"),
        "final_user_action": action_summary["final_user_action"],
        "action_requested": action_summary["action_requested"],
        "action_executed": action_summary["action_executed"],
        "simulated_trade_occurred": action_summary["simulated_trade_occurred"],
        "block_reason": action_summary["block_reason"],
        "human_review_reason": action_summary["human_review_reason"],
        "account_summary": summary,
        "positions_view": positions_view,
        "positions_count": len(positions_view),
        "human_review_items": human_review_items,
        "risk_status": risk_status,
        "next_day_watch_conditions": next_day_watch_conditions,
        "market_state": market_data.get("market_snapshot", {}).get("market_state", "UNKNOWN"),
        "market_data_data_source": market_data.get("data_source"),
        "candidate_pool": candidate_pool,
        "sample_data_notice": "本报告使用本地样例数据，不代表真实市场判断。",
        "feishu_summary": feishu_summary,
        "real_market_data_connected": False,
        "tushare_connected": False,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
    }
    write_json(daily_report_json, payload)

    feishu_message_md.write_text(
        build_feishu_message(trade_date, summary, positions_view, action_summary, human_review_items, next_day_watch_conditions),
        encoding="utf-8",
    )

    reading_report = {
        "dated_local_input_supported": True,
        "trade_date": trade_date,
        "state_file_used": str(state_file_used),
        "daily_decision_file_used": str(daily_decision_file_used) if daily_decision_file_used else "",
        "trade_log_file_used": str(trade_log_file_used) if trade_log_file_used else "",
        "market_data_file_used": str(market_data_file_used),
        "market_data_is_template": market_data_is_template,
        "market_data_is_sample": market_data_is_sample,
        "candidate_pool_file_used": str(candidate_pool_file_used),
        "candidate_pool_is_template": candidate_pool_is_template,
        "candidate_pool_is_sample": candidate_pool_is_sample,
        "human_review_items_count": len(human_review_items),
        "positions_count": len(positions_view),
        "daily_report_generated": True,
        "final_user_action": action_summary["final_user_action"],
        "action_executed": action_summary["action_executed"],
        "real_market_data_connected": False,
        "tushare_connected": False,
        "real_account_connected": False,
        "auto_trading_enabled": False,
        "full_pipeline_enabled": False,
        "news_module_enabled": False,
        "recommended_next_step": "connect dated daily decision output and updater output into one repeatable simulated live daily workflow",
    }
    reading_report_json, reading_report_md = write_reading_report(trade_date, reading_report)

    print(
        json.dumps(
            {
                "daily_report_md": str(daily_report_md),
                "daily_report_json": str(daily_report_json),
                "feishu_message_md": str(feishu_message_md),
                "reading_report_json": str(reading_report_json),
                "reading_report_md": str(reading_report_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
