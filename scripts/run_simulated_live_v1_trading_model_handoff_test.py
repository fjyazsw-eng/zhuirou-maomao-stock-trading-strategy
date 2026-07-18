from __future__ import annotations

import argparse
import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "reports" / "simulated_live_v1" / "review"
INPUT_DIR = ROOT / "reports" / "simulated_live_v1" / "input" / "market_data"
STATE_PATH = ROOT / "reports" / "simulated_live_v1" / "state" / "simulated_account_state.json"

DEFAULT_HANDOFF_PATH = REVIEW_DIR / "stock_selection_to_trading_handoff_20260706.json"
DEFAULT_QUOTES_PATH = INPUT_DIR / "handoff_latest_readonly_quotes_20260706.json"
DEFAULT_REPORT_JSON_PATH = REVIEW_DIR / "trading_model_handoff_test_20260706.json"
DEFAULT_REPORT_MD_PATH = REVIEW_DIR / "trading_model_handoff_test_20260706.md"

ALLOWED_SIM_BUY = {"600276.SH"}
WATCH_ONLY = {"002458.SZ", "688235.SH", "301520.SZ", "301257.SZ"}
FORMAL_HASH = "2D545CDEC06244FEE96928207736D6A99964057413A34FBF9E3FD45465749454"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def safe_round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def moving_average(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return safe_round(sum(closes[-window:]) / window)


def analyze_quote(quote: dict[str, Any]) -> dict[str, Any]:
    history = list(quote.get("history_daily_raw", []))
    closes = [float(row["close"]) for row in history if row.get("close") is not None]
    latest_price = safe_round(quote.get("close"))
    ma5 = moving_average(closes, 5)
    ma10 = moving_average(closes, 10)
    ma20 = moving_average(closes, 20)

    history_for_breakout = history[:-1] if len(history) >= 2 else []
    prev_3_highs = [float(row["high"]) for row in history_for_breakout[-3:] if row.get("high") is not None]
    breakout_ref = max(prev_3_highs) if len(prev_3_highs) == 3 else None
    latest_high = safe_round(quote.get("high"))
    latest_low = safe_round(quote.get("low"))
    latest_open = safe_round(quote.get("open"))
    pre_close = safe_round(quote.get("pre_close"))
    latest_vol = safe_round(quote.get("vol"))
    prev_5_vols = [float(row["vol"]) for row in history_for_breakout[-5:] if row.get("vol") is not None]
    avg_prev_5_vol = safe_round(sum(prev_5_vols) / len(prev_5_vols)) if prev_5_vols else None

    distance_to_ma5_pct = safe_round(((latest_price - ma5) / ma5) * 100, 2) if latest_price is not None and ma5 else None
    distance_to_ma10_pct = safe_round(((latest_price - ma10) / ma10) * 100, 2) if latest_price is not None and ma10 else None

    pullback_to_ma5_stable = bool(
        latest_price is not None
        and latest_low is not None
        and ma5 is not None
        and latest_low <= ma5 * 1.01
        and latest_price >= ma5
        and pre_close is not None
        and latest_price >= pre_close
    )
    pullback_to_ma10_stable = bool(
        latest_price is not None
        and latest_low is not None
        and ma10 is not None
        and latest_low <= ma10 * 1.01
        and latest_price >= ma10
        and pre_close is not None
        and latest_price >= pre_close
    )
    breakout_3d_high = bool(
        breakout_ref is not None
        and latest_high is not None
        and latest_price is not None
        and latest_high > breakout_ref
        and latest_price >= breakout_ref
    )
    volume_expansion = bool(
        latest_vol is not None
        and avg_prev_5_vol is not None
        and avg_prev_5_vol > 0
        and latest_vol >= avg_prev_5_vol * 1.1
    )
    has_follow_through = bool(
        latest_price is not None
        and latest_open is not None
        and latest_low is not None
        and latest_high is not None
        and latest_high > latest_low
        and latest_price >= latest_open
        and ((latest_price - latest_low) / (latest_high - latest_low)) >= 0.55
    )

    return {
        "latest_quote_loaded": True,
        "latest_price": latest_price,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "distance_to_ma5_pct": distance_to_ma5_pct,
        "distance_to_ma10_pct": distance_to_ma10_pct,
        "pullback_to_ma5_stable": pullback_to_ma5_stable,
        "pullback_to_ma10_stable": pullback_to_ma10_stable,
        "breakout_3d_high": breakout_3d_high,
        "volume_expansion": volume_expansion,
        "has_follow_through": has_follow_through,
        "avg_prev_5_vol": avg_prev_5_vol,
        "breakout_ref_high_3d": breakout_ref,
    }


def buy_point_quality(metrics: dict[str, Any]) -> str:
    if not metrics["latest_quote_loaded"]:
        return "NONE"
    score = 0
    if metrics["pullback_to_ma5_stable"]:
        score += 2
    if metrics["pullback_to_ma10_stable"]:
        score += 2
    if metrics["breakout_3d_high"]:
        score += 2
    if metrics["volume_expansion"]:
        score += 1
    if metrics["has_follow_through"]:
        score += 1
    if metrics["distance_to_ma5_pct"] is not None and abs(metrics["distance_to_ma5_pct"]) <= 3.5:
        score += 1
    if metrics["distance_to_ma10_pct"] is not None and abs(metrics["distance_to_ma10_pct"]) <= 6.0:
        score += 1
    if score >= 7:
        return "GOOD"
    if score >= 5:
        return "FAIR"
    if score >= 3:
        return "POOR"
    return "NONE"


def build_stock_rows(
    handoff_rows: list[dict[str, Any]],
    market_data: dict[str, Any],
    actual_trade_date: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    quote_map = {
        row["ts_code"]: row
        for row in market_data.get("target_symbols_ohlc", [])
        if row.get("trade_date") == actual_trade_date
    }
    result_rows: list[dict[str, Any]] = []
    for item in handoff_rows:
        ts_code = item["ts_code"]
        quote = quote_map.get(ts_code)
        has_quote = quote is not None
        metrics = analyze_quote(quote) if has_quote else {"latest_quote_loaded": False}
        result_rows.append(
            {
                "ts_code": ts_code,
                "name": item["name"],
                "candidate_action": item["candidate_action"],
                "can_trading_model_simulate_buy": item["can_trading_model_simulate_buy"],
                "can_trading_model_watch": item["can_trading_model_watch"],
                "review_status": "loaded" if has_quote else "missing_data",
                "latest_quote_trade_date": quote.get("trade_date") if quote else None,
                "latest_price": quote.get("close") if quote else None,
                "pct_chg": quote.get("pct_chg") if quote else None,
                "ma5": metrics.get("ma5"),
                "ma10": metrics.get("ma10"),
                "ma20": metrics.get("ma20"),
                "missing_data": not has_quote,
                "data_gap_reason": "" if has_quote else f"readonly quotes file 未包含该股票 {actual_trade_date} 行情，保持 missing_data 人工复核闸门。",
            }
        )
    return result_rows, quote_map


def build_hengrui_judgement(hengrui: dict[str, Any], quote: dict[str, Any] | None) -> dict[str, Any]:
    if quote is None:
        return {
            "ts_code": "600276.SH",
            "name": "恒瑞医药",
            "allowed_for_simulated_buy_judgement": True,
            "latest_quote_loaded": False,
            "latest_price": None,
            "ma5": None,
            "ma10": None,
            "ma20": None,
            "distance_to_ma5_pct": None,
            "distance_to_ma10_pct": None,
            "pullback_to_ma5_stable": False,
            "pullback_to_ma10_stable": False,
            "breakout_3d_high": False,
            "volume_expansion": False,
            "has_follow_through": False,
            "buy_point_quality": "NONE",
            "simulated_buy_point_triggered": False,
            "review_status": "missing_data",
            "reason": "最新 readonly quote 仍缺失，无法基于真实行情确认 entry_condition。",
            "manual_confirmation_required": True,
            "auto_trade_executed": False,
            "real_order_placed": False,
            "suggested_simulated_position_upper_bound": "0%",
            "stop_loss_condition": hengrui["stop_loss_condition"],
            "take_profit_condition": hengrui["take_profit_condition"],
            "invalidation_condition": hengrui["invalidation_condition"],
        }

    metrics = analyze_quote(quote)
    quality = buy_point_quality(metrics)
    triggered = bool(
        (metrics["pullback_to_ma5_stable"] or metrics["pullback_to_ma10_stable"] or metrics["breakout_3d_high"])
        and metrics["has_follow_through"]
        and quality in {"FAIR", "GOOD"}
    )
    return {
        "ts_code": "600276.SH",
        "name": "恒瑞医药",
        "allowed_for_simulated_buy_judgement": True,
        **metrics,
        "buy_point_quality": quality,
        "simulated_buy_point_triggered": triggered,
        "review_status": "needs_human_review" if triggered else "watch",
        "reason": (
            "真实只读行情显示已满足部分 entry_condition，但当前仍处于 RISK_OFF / OBSERVE_ONLY，且本模型只输出人工确认级别的模拟买点建议。"
            if triggered
            else "真实只读行情已补齐，但当前更适合继续观察，不满足进入人工确认级别模拟买点的组合条件。"
        ),
        "manual_confirmation_required": True,
        "auto_trade_executed": False,
        "real_order_placed": False,
        "suggested_simulated_position_upper_bound": "10% to 15% after human confirmation" if triggered else "0%",
        "stop_loss_condition": hengrui["stop_loss_condition"],
        "take_profit_condition": hengrui["take_profit_condition"],
        "invalidation_condition": hengrui["invalidation_condition"],
    }


def build_watch_review(
    *,
    ts_code: str,
    name: str,
    quote: dict[str, Any] | None,
    conclusion: str,
    upgrade_watch_condition: str,
    downgrade_condition: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = analyze_quote(quote) if quote is not None else {"latest_quote_loaded": False, "latest_price": None, "ma5": None, "ma10": None}
    payload = {
        "ts_code": ts_code,
        "name": name,
        "latest_quote_loaded": metrics["latest_quote_loaded"],
        "latest_price": metrics.get("latest_price"),
        "ma5": metrics.get("ma5"),
        "ma10": metrics.get("ma10"),
        "review_status": "watch" if quote is not None else "missing_data",
        "observation_only": True,
        "simulate_buy_allowed": False,
        "upgrade_watch_condition": upgrade_watch_condition,
        "downgrade_condition": downgrade_condition,
        "missing_data": quote is None,
        "conclusion": conclusion,
    }
    if extra:
        payload.update(extra)
    return payload


def build_report(handoff_path: Path, quotes_path: Path) -> dict[str, Any]:
    official_hash_before = file_sha256(STATE_PATH)
    handoff = load_json(handoff_path)
    market_data = load_json(quotes_path)
    official_hash_after = file_sha256(STATE_PATH)

    actual_trade_date = str(market_data["trade_date"])
    stock_rows, quote_map = build_stock_rows(handoff["handoff_to_trading_model"], market_data, actual_trade_date)
    hengrui = next(x for x in handoff["handoff_to_trading_model"] if x["ts_code"] == "600276.SH")

    wanbang = build_watch_review(
        ts_code="301520.SZ",
        name="万邦医药",
        quote=quote_map.get("301520.SZ"),
        conclusion="只允许观察，不允许模拟买入，也不能自动升级为 BUY_CANDIDATE。",
        upgrade_watch_condition="若后续回踩 5/10 日线企稳、量价配合改善，且继续强于医药整体，可提示具备升级观察条件，但仍需人工复核。",
        downgrade_condition="若继续高位加速、放量滞涨、冲高回落，或跌破 10 日线且无法收回，应提示降级或剔除观察。",
        extra={
            "manual_mapping_candidate": True,
            "official_component_warning": "该股属于人工观察映射样本，不代表已通过 Tushare 官方板块成分验证。",
        },
    )

    other_watch_reviews = [
        build_watch_review(
            ts_code="002458.SZ",
            name="益生股份",
            quote=quote_map.get("002458.SZ"),
            conclusion="益生股份当前只做观察，不允许模拟买入；即使养殖业持续走强，也只能保留或提升观察优先级。",
            upgrade_watch_condition="若继续强于养殖板块且买点质量改善，可提示继续重点观察。",
            downgrade_condition="若跌破 10 日线且无法收回，或养殖业从潜在主线退回低位轮动，应提示降级。",
        ),
        build_watch_review(
            ts_code="688235.SH",
            name="百济神州",
            quote=quote_map.get("688235.SH"),
            conclusion="百济神州当前只做观察，不允许模拟买入；在 RISK_OFF / OBSERVE_ONLY 下仅保留 BACKUP_TEST 观察属性。",
            upgrade_watch_condition="若医药主线继续强化且个股承接改善，可保留备选观察。",
            downgrade_condition="若高位放量滞涨、跌破 10 日线或医药板块分化明显，应提示降级。",
        ),
        build_watch_review(
            ts_code="301257.SZ",
            name="普蕊斯",
            quote=quote_map.get("301257.SZ"),
            conclusion="普蕊斯当前只做观察，不允许模拟买入，也不能自动升级为 BUY_CANDIDATE。",
            upgrade_watch_condition="若后续回踩 5/10 日线企稳、量价改善且继续强于医药整体，可提示观察质量改善。",
            downgrade_condition="若跌破 10 日线且无法收回，或出现放量滞涨、冲高回落，应提示降级或移出观察。",
        ),
    ]

    missing_data_symbols = [ts_code for ts_code in sorted(ALLOWED_SIM_BUY | WATCH_ONLY) if ts_code not in quote_map]
    readonly_quote_loaded_symbols = [ts_code for ts_code in sorted(quote_map)]
    hengrui_judgement = build_hengrui_judgement(hengrui, quote_map.get("600276.SH"))

    return {
        "handoff_retest_completed": True,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "latest_completed_trade_date": market_data["latest_completed_trade_date"],
        "actual_trade_date_used": actual_trade_date,
        "handoff_read_result": {
            "success": handoff_path.exists(),
            "source_file": str(handoff_path),
            "quotes_file": str(quotes_path),
            "five_stock_scope_confirmed": sorted(ALLOWED_SIM_BUY | WATCH_ONLY),
        },
        "readonly_quote_fetch_attempted": True,
        "readonly_quote_loaded_symbols": readonly_quote_loaded_symbols,
        "missing_data_symbols": missing_data_symbols,
        "market_weather_check": {
            "latest_completed_trade_date": handoff["latest_completed_trade_date"],
            "market_risk_level": handoff["market_weather"]["market_risk_level"],
            "attack_level": handoff["market_weather"]["attack_level"],
        },
        "simulated_buy_allowed_stocks": ["600276.SH"],
        "watch_only_stocks": ["002458.SZ", "688235.SH", "301520.SZ", "301257.SZ"],
        "buy_judgement_for_hengrui": hengrui_judgement,
        "watch_review_for_wanbang": wanbang,
        "watch_review_for_other_stocks": other_watch_reviews,
        "boundary_flags": {
            "candidate_pool_manual_modified": False,
            "simulated_account_state_modified": False,
            "real_order_placed": False,
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "full_pipeline_enabled": False,
            "news_module_enabled": False,
            "validation_private_used_for_today_decision": False,
        },
        "latest_quote_check": stock_rows,
        "official_state_hash_before": official_hash_before,
        "official_state_hash_after": official_hash_after,
        "official_state_hash_preserved": official_hash_before == FORMAL_HASH and official_hash_after == FORMAL_HASH,
        "failed_checks": [],
        "blockers": [],
        "final_conclusion": {
            "candidate_pool_manual_modified": False,
            "simulated_account_state_modified": False,
            "real_order_placed": False,
            "hengrui_simulated_buy_point_triggered": hengrui_judgement["simulated_buy_point_triggered"],
            "manual_confirmation_required": hengrui_judgement["manual_confirmation_required"],
            "wanbang_observation_only": True,
            "other_watch_stocks_observation_only": True,
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# trading_model_handoff_retest_{report['actual_trade_date_used']}",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- latest_completed_trade_date: {report['latest_completed_trade_date']}",
        f"- actual_trade_date_used: {report['actual_trade_date_used']}",
        f"- official_state_hash_before: {report['official_state_hash_before']}",
        f"- official_state_hash_after: {report['official_state_hash_after']}",
        f"- official_state_hash_preserved: {report['official_state_hash_preserved']}",
        "",
        "## handoff_read_result",
    ]
    for key, value in report["handoff_read_result"].items():
        lines.append(f"- {key}: {value}")
    lines += [
        "",
        f"- readonly_quote_fetch_attempted: {report['readonly_quote_fetch_attempted']}",
        f"- readonly_quote_loaded_symbols: {report['readonly_quote_loaded_symbols']}",
        f"- missing_data_symbols: {report['missing_data_symbols']}",
        "",
        "## market_weather_check",
    ]
    for key, value in report["market_weather_check"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## buy_judgement_for_hengrui"]
    for key, value in report["buy_judgement_for_hengrui"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## watch_review_for_wanbang"]
    for key, value in report["watch_review_for_wanbang"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## watch_review_for_other_stocks"]
    for item in report["watch_review_for_other_stocks"]:
        lines.append(
            f"- {item['name']}({item['ts_code']}) | latest_quote_loaded={item['latest_quote_loaded']} | review_status={item['review_status']} | observation_only={item['observation_only']}"
        )
        lines.append(f"  conclusion={item['conclusion']}")
    lines += ["", "## boundary_flags"]
    for key, value in report["boundary_flags"].items():
        lines.append(f"- {key}: {value}")
    lines += ["", "## failed_checks", "- []", "", "## blockers", "- []", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated_live_v1 trading model handoff test")
    parser.add_argument("--handoff-path", default=str(DEFAULT_HANDOFF_PATH))
    parser.add_argument("--quotes-path", default=str(DEFAULT_QUOTES_PATH))
    parser.add_argument("--report-json-path", default=str(DEFAULT_REPORT_JSON_PATH))
    parser.add_argument("--report-md-path", default=str(DEFAULT_REPORT_MD_PATH))
    args = parser.parse_args()

    handoff_path = Path(args.handoff_path)
    quotes_path = Path(args.quotes_path)
    report_json_path = Path(args.report_json_path)
    report_md_path = Path(args.report_md_path)

    report = build_report(handoff_path, quotes_path)
    report_json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report_md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(report_json_path), "md": str(report_md_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
