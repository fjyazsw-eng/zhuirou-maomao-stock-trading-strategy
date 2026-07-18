from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "reports" / "simulated_live_v1" / "review"
SOURCE_PATH = ROOT / "scripts" / "run_simulated_live_v1_stock_selection_research_focus_sectors.py"


spec = importlib.util.spec_from_file_location("focus_research", SOURCE_PATH)
assert spec and spec.loader
focus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(focus)


KEY_SECTORS = [
    "化学制药",
    "创新药",
    "生物制品",
    "医疗研发外包（884244）",
    "养殖业",
    "半导体",
    "电子化学品",
    "存储芯片",
    "券商",
    "低位消费修复",
    "低位周期修复",
]


def safe_float(value: Any, digits: int = 2) -> float | None:
    return focus.safe_float(value, digits)


def compute_mainline_score(sector: dict[str, Any]) -> int:
    score = 50.0
    score += (sector.get("pct_chg_1d") or 0) * 0.8
    score += (sector.get("pct_chg_5d") or 0) * 1.2
    score += (sector.get("pct_chg_10d") or 0) * 1.1
    score += (sector.get("pct_chg_20d") or 0) * 0.8
    score += (sector.get("amount_change") or 0) * 0.15
    score += ((sector.get("up_ratio") or 0) - 50) * 0.3
    score += 5 if sector.get("has_persistence") else -4
    score += 4 if sector.get("is_low_starting") else 0
    score -= 8 if sector.get("is_high_speeding") else 0
    score += 5 if sector.get("TREND_LEADER") or sector.get("ABSOLUTE_LEADER") else -5
    score += 4 if sector.get("CAPACITY_CORE") else -2
    score += 2 if sector.get("ELASTIC_LEADER") else 0
    score += 2 if sector.get("LOW_POSITION_REPAIR") else 0
    if sector.get("sector_state") == "RETREATING":
        score -= 18
    if sector.get("sector_name") == "券商":
        score -= 6
    if sector.get("sector_name") == "医疗研发外包（884244）":
        score = min(score, 45)
    return max(0, min(100, round(score)))


def infer_sector_nature(sector: dict[str, Any], score: int) -> str:
    name = sector["sector_name"]
    state = sector.get("sector_state")
    if name == "券商":
        return "SENTIMENT_INDICATOR"
    if name == "医疗研发外包（884244）" or sector.get("missing_data"):
        return "WATCH_ONLY"
    if name in {"半导体", "电子化学品", "存储芯片"} and state == "RETREATING":
        return "RETREAT_WARNING"
    if name == "养殖业":
        return "POTENTIAL_MAINLINE" if score >= 65 else "LOW_POSITION_REPAIR"
    if name in {"化学制药", "创新药", "生物制品"}:
        if score >= 80:
            return "STAGE_MAINLINE"
        if score >= 65:
            return "POTENTIAL_MAINLINE"
        return "LONG_TERM_CAPITAL_THEME"
    if score >= 80:
        return "STAGE_MAINLINE"
    if score >= 65:
        return "POTENTIAL_MAINLINE"
    if score >= 50:
        return "LOW_POSITION_REPAIR"
    if score >= 30:
        return "EMOTION_HOTSPOT"
    return "RETREAT_WARNING"


def attach_sector_meta(sectors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for sector in sectors:
        item = dict(sector)
        score = compute_mainline_score(item)
        item["mainline_score_0_100"] = score
        item["sector_nature"] = infer_sector_nature(item, score)
        item["missing_policy_news_data"] = True
        item["policy_news_watch"] = {
            "policy_support_level": "UNKNOWN",
            "policy_evidence": None,
            "industry_logic": industry_logic(item["sector_name"]),
            "news_risk": "UNKNOWN",
            "policy_data_source": "missing",
        }
        rows.append(item)
    return rows


def industry_logic(name: str) -> str:
    mapping = {
        "化学制药": "医药研发与仿创升级，中长期受创新药与产业升级逻辑支撑。",
        "创新药": "创新管线、医保谈判和长期研发投入驱动，但短线波动较大。",
        "生物制品": "疫苗、血制品和创新生物药具备中长期产业逻辑。",
        "医疗研发外包（884244）": "CXO/CDMO 具备产业链服务逻辑，但当前缺少可靠正式成分验证。",
        "养殖业": "供给周期与价格修复驱动，偏低位修复逻辑。",
        "半导体": "国产替代和先进制造是长期逻辑，但当前位置需看退潮/修复切换。",
        "电子化学品": "上游材料受国产替代和先进工艺推进支持。",
        "存储芯片": "景气修复和国产替代存在逻辑，但当前主题验证不足。",
        "券商": "主要反映市场风险偏好和交投情绪。",
        "低位消费修复": "低估值消费轮动与内需修复预期。",
        "低位周期修复": "顺周期估值修复与库存周期博弈。",
    }
    return mapping.get(name, "待补充。")


def sector_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["sector_name"]: row for row in rows}


def build_sector_buckets(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    short_term = [x for x in rows if x["sector_nature"] in {"STAGE_MAINLINE", "POTENTIAL_MAINLINE", "EMOTION_HOTSPOT", "LOW_POSITION_REPAIR"}][:6]
    mid_long = [x for x in rows if x["sector_nature"] in {"STAGE_MAINLINE", "POTENTIAL_MAINLINE", "LONG_TERM_CAPITAL_THEME"}][:6]
    emotion = [x for x in rows if x["sector_nature"] == "EMOTION_HOTSPOT"][:6]
    retreat = [x for x in rows if x["sector_nature"] == "RETREAT_WARNING"][:6]
    long_term = [x for x in rows if x["sector_nature"] == "LONG_TERM_CAPITAL_THEME"][:6]
    low_pos = [x for x in rows if x["sector_nature"] == "LOW_POSITION_REPAIR"][:6]
    return {
        "short_term_sector_candidates": short_term,
        "mid_long_term_sector_candidates": mid_long,
        "emotion_hotspot_watchlist": emotion,
        "retreat_warning_sectors": retreat,
        "long_term_capital_themes": long_term,
        "low_position_repair_candidates": low_pos,
        "current_stage_mainlines": [x for x in rows if x["sector_nature"] == "STAGE_MAINLINE"][:4],
        "potential_next_mainlines": [x for x in rows if x["sector_nature"] == "POTENTIAL_MAINLINE"][:4],
    }


def enrich_continuity(review_rows: list[dict[str, Any]], sector_meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in review_rows:
        item = dict(row)
        sector_name = item["sector"]
        lookup_name = sector_name if sector_name in sector_meta else f"{sector_name}（884244）" if sector_name == "医疗研发外包" else sector_name
        meta = sector_meta.get(lookup_name, {})
        item["sector_nature"] = meta.get("sector_nature", "WATCH_ONLY")
        item["mainline_score_0_100"] = meta.get("mainline_score_0_100", 40 if item.get("manual_mapping_candidate") else 50)
        item["short_term_logic"] = short_term_logic(item, meta)
        item["mid_long_term_logic"] = mid_long_term_logic(item, meta)
        item["invalidation_condition"] = item.get("stop_loss_condition")
        out.append(item)
    return out


def short_term_logic(item: dict[str, Any], sector_meta: dict[str, Any]) -> str:
    return f"{item['sector']} 当前板块性质={sector_meta.get('sector_nature','WATCH_ONLY')}，短线看资金连续性、龙头承接和5/10日线买点。"


def mid_long_term_logic(item: dict[str, Any], sector_meta: dict[str, Any]) -> str:
    return f"{item['sector']} 中长期看产业逻辑、20日/60日趋势和容量核心持续性。"


def refine_model_test_pool(pool: list[dict[str, Any]], continuity_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in pool:
        detail = continuity_map[item["ts_code"]]
        rows.append(
            {
                "ts_code": item["ts_code"],
                "name": item["name"],
                "sector": detail["sector"],
                "sector_nature": detail["sector_nature"],
                "mainline_score_0_100": detail["mainline_score_0_100"],
                "test_role": item["test_role"],
                "previous_action": detail["previous_action"],
                "current_action": detail["current_action"],
                "action_change_reason": detail["action_change_reason"],
                "manual_mapping_candidate": detail.get("manual_mapping_candidate", False),
                "can_simulate_buy_signal": item["can_simulate_buy_signal"] and detail["buy_point_quality"] != "POOR",
                "can_simulate_watch_signal": item["can_simulate_watch_signal"],
                "short_term_logic": detail["short_term_logic"],
                "mid_long_term_logic": detail["mid_long_term_logic"],
                "entry_condition": detail["entry_condition"],
                "stop_loss_condition": detail["stop_loss_condition"],
                "take_profit_condition": detail["take_profit_condition"],
                "invalidation_condition": detail["invalidation_condition"],
                "main_risks": detail["main_risks"],
            }
        )
    return rows


def consultation_template() -> dict[str, Any]:
    return {
        "summary": "一句话结论",
        "current_action": "BUY_CANDIDATE / WATCH / WATCH_ONLY / OBSERVE / NEEDS_HUMAN_REVIEW",
        "market_weather": {"market_risk_level": "", "attack_level": ""},
        "sector_nature": "",
        "mainline_score_0_100": 0,
        "direction_type": "情绪热点 / 阶段主线 / 潜在主线 / 长期方向 / 退潮方向",
        "leader_status": "",
        "stock_position": "",
        "capital_flow": "",
        "short_term_entry": "",
        "mid_long_term_logic": "",
        "stop_loss_condition": "",
        "take_profit_condition": "",
        "do_not_participate_if": "",
        "suitable_for_model_test_candidate_pool": False,
        "suggest_formal_candidate_pool_manual": False,
    }


def build_feishu_daily_template(report_date: str, latest_trade_date: str, market_weather: dict[str, Any], buckets: dict[str, list[dict[str, Any]]], stock_review: list[dict[str, Any]], model_test_pool: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "report_date": report_date,
        "latest_completed_trade_date": latest_trade_date,
        "market_weather": market_weather,
        "short_term_market_view": "弱市环境下只看高确定性回踩与观察升级信号。",
        "mid_long_term_market_view": "医药部分细分方向具备中期逻辑，但当前位置仍需确认持续性。",
        "current_stage_mainlines": buckets["current_stage_mainlines"],
        "potential_next_mainlines": buckets["potential_next_mainlines"],
        "long_term_capital_themes": buckets["long_term_capital_themes"],
        "emotion_hotspot_watchlist": buckets["emotion_hotspot_watchlist"],
        "low_position_repair_candidates": buckets["low_position_repair_candidates"],
        "retreat_warning_sectors": buckets["retreat_warning_sectors"],
        "policy_news_watch": {"missing_policy_news_data": True, "items": []},
        "capital_flow_summary": "仅使用行情、成交额与个股资金字段；暂无可靠政策/新闻接入。",
        "short_term_stock_candidates": [x for x in stock_review if x["current_action"] in {"BUY_CANDIDATE", "WATCH"}][:5],
        "mid_long_term_stock_candidates": [x for x in stock_review if x["sector_nature"] in {"STAGE_MAINLINE", "LONG_TERM_CAPITAL_THEME", "POTENTIAL_MAINLINE"}][:5],
        "watch_only_candidates": [x for x in stock_review if x["current_action"] in {"WATCH", "WATCH_ONLY"}][:8],
        "model_test_candidate_pool": model_test_pool,
        "risk_alerts": ["弱市仍未改善，追高容错率低。", "半导体若无进一步共振，不宜强判二次启动。"],
        "tomorrow_watch_conditions": ["券商是否放量带动市场。", "恒瑞医药是否继续保持回踩承接。", "养殖业是否继续强于大盘。"],
        "model_self_check": ["是否错误把情绪热点当主线。", "是否在弱市中给出过宽 BUY_CANDIDATE。", "manual mapping 是否被误当正式成分。"],
        "proposed_actions_for_human_review": ["继续保留 3-5 只 model_test_candidate_pool 做升降级测试。"],
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# stock_selection_model_test_pool_{report['latest_completed_trade_date']}",
        "",
        f"- latest_completed_trade_date: {report['latest_completed_trade_date']}",
        f"- market_risk_level: {report['market_weather']['market_risk_level']}",
        f"- attack_level: {report['market_weather']['attack_level']}",
        f"- recommend_update_candidate_pool_manual: {report['recommend_update_candidate_pool_manual']}",
        "",
        "## 主线识别",
    ]
    for item in report["focus_sector_summary"]:
        lines.append(f"- {item['sector_name']} | nature={item['sector_nature']} | score={item['mainline_score_0_100']} | state={item['sector_state']}")
    lines += ["", "## 候选池复核"]
    for item in report["candidate_continuity_review"]:
        lines.append(f"- {item['name']}({item['ts_code']}) | prev={item['previous_action']} | current={item['current_action']} | nature={item['sector_nature']}")
    lines += ["", "## model_test_candidate_pool"]
    for item in report["model_test_candidate_pool"]:
        lines.append(f"- {item['name']}({item['ts_code']}) | role={item['test_role']} | action={item['current_action']} | buy_signal={item['can_simulate_buy_signal']}")
    lines += ["", "## 最终判断"]
    for k, v in report["final_judgement"].items():
        lines.append(f"- {k}: {v}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    # Rebuild latest focus-sector report first.
    pro = focus.get_tushare_pro()
    latest_trade_date, open_dates = focus.latest_completed_trade_date(pro)
    trade_dates = focus.get_trade_window(open_dates, latest_trade_date, 121)
    anchors = focus.anchor_dates(trade_dates)
    fetch_dates = sorted(set(trade_dates[-25:] + list(anchors.values())))

    daily = focus.fetch_daily_by_dates(pro, fetch_dates)
    latest_daily = daily[daily["trade_date"] == latest_trade_date].copy()
    daily_basic = focus.fetch_latest_daily_basic(pro, latest_trade_date)
    moneyflow = focus.fetch_latest_moneyflow(pro, latest_trade_date)
    index_history = focus.fetch_index_history(pro, trade_dates[0], latest_trade_date)
    stock_basic = focus.load_stock_basic()
    sw_classify = focus.fetch_sw_classify(pro)

    focus_codes: list[str] = []
    for item in focus.FOCUS_SECTORS:
        if item["mapping_type"] in {"sw_l2", "sw_l3", "explicit_external_code"}:
            focus_codes.append(item["index_code"])
        else:
            focus_codes.extend(item.get("proxy_codes", []))
    focus_codes = sorted(set(focus_codes))
    member_df = focus.fetch_members_for_codes(pro, focus_codes)
    member_df = member_df.merge(sw_classify[["index_code", "industry_name"]], on="index_code", how="left")
    member_df.rename(columns={"industry_name": "sector_name"}, inplace=True)
    l2_members = member_df[member_df["index_code"].str.startswith("801")].drop_duplicates(subset=["index_code", "con_code"])[["index_code", "con_code", "con_name", "sector_name"]].rename(columns={"con_code": "ts_code", "con_name": "name"})

    latest_daily = latest_daily.merge(stock_basic, on="ts_code", how="left")
    if not daily_basic.empty:
        latest_daily = latest_daily.merge(daily_basic.drop(columns=["trade_date"]), on="ts_code", how="left")
    if not moneyflow.empty:
        latest_daily = latest_daily.merge(moneyflow.drop(columns=["trade_date"]), on="ts_code", how="left")
        latest_daily["main_force_net"] = (latest_daily["buy_lg_amount"].fillna(0) - latest_daily["sell_lg_amount"].fillna(0)) + (latest_daily["buy_elg_amount"].fillna(0) - latest_daily["sell_elg_amount"].fillna(0))

    close_pivot = daily.pivot_table(index="ts_code", columns="trade_date", values="close", aggfunc="last")
    latest_enriched = focus.add_return_columns(latest_daily, close_pivot, anchors)
    stock_table = focus.build_stock_features(daily, latest_enriched)
    stock_table = focus.add_volume_amount_change_metrics(daily, stock_table)
    market_weather = focus.calc_market_weather(index_history, anchors, latest_daily, daily)
    sector_table = focus.build_l2_sector_table(stock_table, daily, l2_members, latest_trade_date)
    auto_discovery_result = focus.auto_discovery(sector_table)

    focus_sector_records = []
    all_stocks = []
    missing_data = []
    for definition in focus.FOCUS_SECTORS:
        sector_record, stock_rows, missing = focus.build_focus_sector_record(definition, member_df, stock_table, daily, latest_trade_date, market_weather)
        focus_sector_records.append(sector_record)
        all_stocks.extend(stock_rows)
        missing_data.extend(missing)

    manual_observation_stocks, manual_pool_entries = focus.analyze_manual_focus_stocks(stock_table, market_weather)
    recommended_candidates, removed_list = focus.build_candidates(all_stocks, market_weather)
    medical_manual_section = {
        "sector_name": "医疗研发外包",
        "sector_code": "884244",
        "data_source_status": "TUSHARE_INDEX_MEMBER_ALL_MISSING",
        "missing_data": True,
        "manual_mapping": True,
        "manual_mapping_source": "同花顺人工观察",
        "sector_state": "WATCH_ONLY",
        "can_rank_full_sector": False,
        "can_select_full_sector_leaders": False,
        "why_missing_data": "当前 Tushare 无法通过 index_member_all 获取 884244 真实成分股。",
        "why_manual_mapping_allowed": "允许使用同花顺人工观察样本股做个股级别跟踪。",
        "sample_stocks": manual_observation_stocks,
        "can_enter_proposed_candidate_pool": "WATCH_ONLY",
        "can_enter_watch_pool": True,
        "can_enter_buy_candidate_pool": False,
        "continue_watch_condition": "回踩关键均线企稳、量价改善、并持续强于医药整体。",
        "next_data_improvement": "补充更可靠的 884244 成分源。",
    }
    recommended_candidates, removed_list, medical_manual_section = focus.apply_manual_policy_overrides(
        recommended_candidates, removed_list, medical_manual_section, market_weather
    )

    sector_rows = attach_sector_meta(focus_sector_records)
    sector_meta = sector_map(sector_rows)
    continuity_raw = focus.build_continuity_review(focus.build_stock_lookup(recommended_candidates, removed_list, medical_manual_section), market_weather)
    continuity_review = enrich_continuity(continuity_raw, sector_meta)
    continuity_map = {x["ts_code"]: x for x in continuity_review}
    model_test_pool = refine_model_test_pool(focus.build_model_test_candidate_pool(continuity_raw), continuity_map)
    buckets = build_sector_buckets(sector_rows)

    report_date = datetime.now().strftime("%Y-%m-%d")
    report = {
        "completed": True,
        "latest_completed_trade_date": latest_trade_date,
        "report_date": report_date,
        "market_weather": market_weather,
        "missing_data": sorted(set(missing_data)),
        "missing_policy_news_data": True,
        "focus_sector_summary": [x for x in sector_rows if x["sector_name"] in KEY_SECTORS],
        "short_term_sector_candidates": buckets["short_term_sector_candidates"],
        "mid_long_term_sector_candidates": buckets["mid_long_term_sector_candidates"],
        "emotion_hotspot_watchlist": buckets["emotion_hotspot_watchlist"],
        "retreat_warning_sectors": buckets["retreat_warning_sectors"],
        "long_term_capital_themes": buckets["long_term_capital_themes"],
        "low_position_repair_candidates": buckets["low_position_repair_candidates"],
        "current_stage_mainlines": buckets["current_stage_mainlines"],
        "potential_next_mainlines": buckets["potential_next_mainlines"],
        "policy_news_watch": {"missing_policy_news_data": True, "items": [x["policy_news_watch"] | {"sector_name": x["sector_name"]} for x in sector_rows if x["sector_name"] in KEY_SECTORS]},
        "candidate_continuity_review": continuity_review,
        "short_term_stock_candidates": [x for x in continuity_review if x["current_action"] in {"BUY_CANDIDATE", "WATCH"}][:5],
        "mid_long_term_stock_candidates": [x for x in continuity_review if x["sector_nature"] in {"STAGE_MAINLINE", "LONG_TERM_CAPITAL_THEME", "POTENTIAL_MAINLINE"}][:5],
        "watch_only_candidates": [x for x in continuity_review if x["current_action"] in {"WATCH", "WATCH_ONLY", "OBSERVE"}][:8],
        "model_test_candidate_pool": model_test_pool,
        "medical_rnd_outsourcing_manual_observation": medical_manual_section,
        "consultation_template": consultation_template(),
        "feishu_daily_template": build_feishu_daily_template(report_date, latest_trade_date, market_weather, buckets, continuity_review, model_test_pool),
        "auto_discovery": auto_discovery_result,
        "capital_flow_summary": "仅基于 Tushare 行情、成交额和可得 moneyflow 字段，未引入真实政策/新闻流。",
        "risk_alerts": ["弱市未改善，追高信号仍需严格约束。", "半导体仍需防范高位退潮误判为二次启动。"],
        "tomorrow_watch_conditions": ["券商是否放量带动市场。", "化学制药/创新药是否继续维持持续性。", "养殖业是否从修复走向潜在主线。"],
        "model_self_check": ["是否区分了情绪热点和阶段主线。", "是否错误放宽了弱市 BUY_CANDIDATE。", "manual mapping 是否保持了独立标记。"],
        "proposed_actions_for_human_review": ["继续用 3-5 只 model_test_candidate_pool 测试升降级和剔除逻辑。"],
        "failed_checks": [],
        "blockers": [],
    }
    final_pool_for_judgement = [{**x, "candidate_action": x["current_action"]} for x in model_test_pool]
    report["final_judgement"] = focus.final_judgement({"market_weather": market_weather}, final_pool_for_judgement)
    report["recommend_update_candidate_pool_manual"] = report["final_judgement"]["recommend_update_candidate_pool_manual"]

    json_path = REVIEW_DIR / f"stock_selection_model_test_pool_{latest_trade_date}.json"
    md_path = REVIEW_DIR / f"stock_selection_model_test_pool_{latest_trade_date}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path), "latest_completed_trade_date": latest_trade_date}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
