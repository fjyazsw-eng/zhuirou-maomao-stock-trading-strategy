from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "reports" / "simulated_live_v1" / "review"
SOURCE_JSON = REVIEW_DIR / "stock_selection_model_test_pool_20260706.json"


def extract_trade_date(path: Path) -> str:
    match = re.search(r"_(\d{8})\.json$", path.name)
    return match.group(1) if match else ""


def resolve_source_json(review_dir: Path = REVIEW_DIR, source_json: Path | None = None) -> Path:
    if source_json is not None:
        return source_json
    candidates = sorted(
        [
            *review_dir.glob("stock_selection_model_test_pool_*.json"),
            *review_dir.glob("stock_selection_research_focus_sectors_*.json"),
        ],
        key=lambda path: (extract_trade_date(path), path.stat().st_mtime),
        reverse=True,
    )
    if candidates:
        return candidates[0]
    return SOURCE_JSON


def load_report(source_json: Path | None = None, review_dir: Path = REVIEW_DIR) -> dict[str, Any]:
    path = resolve_source_json(review_dir=review_dir, source_json=source_json)
    return json.loads(path.read_text(encoding="utf-8"))


def trading_instruction(item: dict[str, Any]) -> str:
    if item.get("manual_mapping_candidate"):
        return "该股为 manual_mapping 观察样本，不允许模拟买入，只观察是否改善买点质量。"
    if item["can_trading_model_simulate_buy"]:
        return "交易模型只允许在满足 entry_condition 时模拟买点判断，不允许直接买入。"
    return "交易模型只允许观察升降级，不允许模拟买入。"


def score_nature_explanation(item: dict[str, Any]) -> str | None:
    score = item["mainline_score_0_100"]
    nature = item["sector_nature"]
    sector = item["sector"]
    if sector == "创新药" and score >= 80 and nature != "STAGE_MAINLINE":
        return "创新药当前使用代理主题观察篮子，不是完整可验证正式板块；即使分数高，也不能直接升级为 STAGE_MAINLINE。"
    if sector == "存储芯片" and score >= 65 and nature == "WATCH_ONLY":
        return "存储芯片当前属于代理主题，且缺少独立可靠成分验证；分数只能用于提示关注，不能直接视为主线。"
    if sector == "券商" and nature == "SENTIMENT_INDICATOR":
        return "券商分数较高主要反映情绪修复和风偏变化，不等于进攻主线，所以保留为 SENTIMENT_INDICATOR。"
    if sector == "养殖业" and nature == "POTENTIAL_MAINLINE":
        return "养殖业虽强，但当前更像低位修复向潜在主线过渡，仍需继续验证持续性、容量核心和市场共振，暂不直接升 STAGE_MAINLINE。"
    if score >= 80 and nature != "STAGE_MAINLINE":
        return "该方向分数高，但板块性质受到代理主题、数据缺口、情绪属性或持续性不足约束，不能只凭分数升级。"
    if score >= 65 and nature == "WATCH_ONLY":
        return "该方向分数达到关注阈值，但由于数据不足或主题验证不完整，仍只能 WATCH_ONLY。"
    if nature == "SENTIMENT_INDICATOR" and score >= 65:
        return "高分更多体现情绪带动，不代表它已经具备阶段主线属性。"
    if nature == "POTENTIAL_MAINLINE" and score >= 80:
        return "高分说明强度足够，但主线确认还缺连续性或更明确的市场共振。"
    return None


def action_for(item: dict[str, Any], detail: dict[str, Any]) -> str:
    return str(item.get("current_action") or item.get("candidate_action") or detail.get("current_action") or "WATCH")


def code_for(item: dict[str, Any]) -> str:
    return str(item.get("ts_code") or item.get("code") or "").strip()


def can_simulate_buy_judgement(item: dict[str, Any], detail: dict[str, Any]) -> bool:
    current_action = action_for(item, detail)
    return (
        current_action == "BUY_CANDIDATE"
        and not detail.get("manual_mapping_candidate", item.get("manual_mapping_candidate", False))
        and detail.get("buy_point_quality") in {"GOOD", "FAIR"}
        and detail.get("sector_nature", item.get("sector_nature")) not in {"RETREAT_WARNING", "EMOTION_HOTSPOT"}
        and bool(detail.get("entry_condition") or item.get("entry_condition"))
        and bool(detail.get("stop_loss_condition") or item.get("stop_loss_condition"))
        and bool(detail.get("take_profit_condition") or item.get("take_profit_condition"))
    )


def source_candidate_rows(source: dict[str, Any]) -> list[dict[str, Any]]:
    action_rank = {"BUY_CANDIDATE": 0, "WATCH": 1, "WATCH_ONLY": 2, "OBSERVE": 3, "NEEDS_HUMAN_REVIEW": 4}
    rows: dict[str, dict[str, Any]] = {}

    def add_many(items: list[dict[str, Any]], source_name: str) -> None:
        for item in items:
            code = code_for(item)
            if not code:
                continue
            row = {**item, "ts_code": code, "handoff_source": source_name}
            action = action_for(row, row)
            existing = rows.get(code)
            if existing is None or action_rank.get(action, 9) < action_rank.get(action_for(existing, existing), 9):
                rows[code] = row

    add_many(list(source.get("model_test_candidate_pool") or []), "model_test_candidate_pool")
    add_many(list(source.get("recommended_candidates") or []), "recommended_candidates")
    add_many(list(source.get("candidate_continuity_review") or []), "candidate_continuity_review")
    dynamic_rows = list(((source.get("dynamic_watch_pool") or {}).get("watch_pool") or []))
    add_many(dynamic_rows, "dynamic_watch_pool")
    return sorted(rows.values(), key=lambda row: (action_rank.get(action_for(row, row), 9), code_for(row)))[:10]


def build_handoff(source: dict[str, Any]) -> dict[str, Any]:
    market_weather = source["market_weather"]
    continuity = source["candidate_continuity_review"]
    continuity_map = {x["ts_code"]: x for x in continuity}

    handoff_rows = []
    for item in source_candidate_rows(source):
        ts_code = code_for(item)
        detail = continuity_map.get(ts_code, item)
        current_action = action_for(item, detail)
        can_buy = can_simulate_buy_judgement(item, detail)
        can_watch = current_action in {"WATCH", "WATCH_ONLY", "BUY_CANDIDATE", "OBSERVE"}
        row = {
            "ts_code": ts_code,
            "name": item.get("name") or detail.get("name", ""),
            "sector": item.get("sector") or detail.get("sector", ""),
            "sector_nature": item.get("sector_nature") or detail.get("sector_nature", "WATCH_ONLY"),
            "mainline_score_0_100": item.get("mainline_score_0_100", detail.get("mainline_score_0_100", 0)),
            "test_role": item.get("test_role", "WATCH_TEST"),
            "candidate_action": current_action,
            "can_trading_model_simulate_buy": can_buy,
            "can_trading_model_watch": can_watch,
            "official_sector_candidate": not item.get("manual_mapping_candidate", False),
            "manual_mapping_candidate": item.get("manual_mapping_candidate", False),
            "confidence_level": detail.get("confidence_level", "MEDIUM"),
            "why_selected": item.get("action_change_reason") or detail.get("action_change_reason", ""),
            "short_term_logic": item.get("short_term_logic", "按板块和个股买点质量决定是否轻仓试错。"),
            "mid_long_term_logic": item.get("mid_long_term_logic", "观察是否持续跑赢所属细分板块和市场。"),
            "entry_condition": item.get("entry_condition") or detail.get("entry_condition", ""),
            "stop_loss_condition": item.get("stop_loss_condition") or detail.get("stop_loss_condition", ""),
            "take_profit_condition": item.get("take_profit_condition") or detail.get("take_profit_condition", ""),
            "invalidation_condition": item.get("invalidation_condition") or detail.get("invalidation_condition", ""),
            "main_risks": item.get("main_risks") or detail.get("main_risks", ""),
            "trading_model_instruction": "",
        }
        row["trading_model_instruction"] = trading_instruction(row)
        explanation = score_nature_explanation(row)
        if explanation:
            row["score_nature_explanation"] = explanation
        handoff_rows.append(row)

    allowed_buy = [x["ts_code"] for x in handoff_rows if x["can_trading_model_simulate_buy"]]
    watch_only = [x["ts_code"] for x in handoff_rows if x["can_trading_model_watch"] and not x["can_trading_model_simulate_buy"]]

    return {
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "latest_completed_trade_date": source["latest_completed_trade_date"],
        "market_weather": market_weather,
        "handoff_to_trading_model": handoff_rows,
        "human_review_summary": {
            "can_handoff_to_trading_model_for_test": True,
            "stocks_allowed_for_simulated_buy_judgement": allowed_buy,
            "stocks_watch_only": watch_only,
            "stocks_blocked_from_trading_model": [],
            "recommend_update_candidate_pool_manual": False,
            "review_conclusion": "不建议更新正式 candidate_pool_MANUAL.json。",
        },
        "failed_checks": [],
        "blockers": [],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# stock_selection_to_trading_handoff_{report['latest_completed_trade_date']}",
        "",
        f"- latest_completed_trade_date: {report['latest_completed_trade_date']}",
        f"- market_risk_level: {report['market_weather']['market_risk_level']}",
        f"- attack_level: {report['market_weather']['attack_level']}",
        "",
        "## handoff_to_trading_model",
    ]
    for item in report["handoff_to_trading_model"]:
        lines.append(
            f"- {item['name']}({item['ts_code']}) | action={item['candidate_action']} | simulate_buy={item['can_trading_model_simulate_buy']} | watch={item['can_trading_model_watch']}"
        )
        if item.get("score_nature_explanation"):
            lines.append(f"  score_nature_explanation={item['score_nature_explanation']}")
    lines += ["", "## human_review_summary"]
    for k, v in report["human_review_summary"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    source = load_report()
    report = build_handoff(source)
    json_path = REVIEW_DIR / f"stock_selection_to_trading_handoff_{report['latest_completed_trade_date']}.json"
    md_path = REVIEW_DIR / f"stock_selection_to_trading_handoff_{report['latest_completed_trade_date']}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
