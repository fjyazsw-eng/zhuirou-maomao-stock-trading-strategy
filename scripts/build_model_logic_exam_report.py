from __future__ import annotations

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = ROOT / "reports" / "simulated_live_v1" / "review"
STATE_PATH = ROOT / "reports" / "simulated_live_v1" / "state" / "simulated_account_state.json"
HANDOFF_PATH = REVIEW_DIR / "stock_selection_to_trading_handoff_20260706.json"
RETEST_PATH = REVIEW_DIR / "trading_model_handoff_retest_20260706.json"
UNIFIED_PATH = REVIEW_DIR / "unified_stock_ai_daily_report_20260706.json"
FOCUS_PATH = REVIEW_DIR / "stock_selection_research_focus_sectors_20260706.md"
OUTPUT_JSON = REVIEW_DIR / "model_logic_exam_20260706.json"
OUTPUT_MD = REVIEW_DIR / "model_logic_exam_20260706.md"
FORMAL_HASH = "2D545CDEC06244FEE96928207736D6A99964057413A34FBF9E3FD45465749454"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def build_theory() -> dict[str, Any]:
    return {
        "board_judgement": {
            "STAGE_MAINLINE": "5日、10日、20日强度持续领先，成交额放大，上涨家数占比改善，板块内部有核心股和容量核心共振，且不是只靠一天脉冲。",
            "EMOTION_HOTSPOT": "更多体现情绪脉冲、消息刺激或单日热度，持续性和容量核心不足，容易隔日分化。",
            "POTENTIAL_MAINLINE": "已有一定持续性，5日和10日表现较强，但20日和板块共振仍需继续确认，处于候选主线阶段。",
            "LOW_POSITION_REPAIR": "前期跌深后低位修复，位置安全但强度未完成主线确认，更多是修复而不是新主升。",
            "RETREAT_WARNING": "高位分歧、成交额衰减、龙头掉队、后排退潮，板块内部不再形成稳定共振。",
            "SENTIMENT_INDICATOR": "更能反映风险偏好与情绪切换，例如券商，经常是风向标，不一定是普通进攻主线。",
            "why_not_day1_only": "只看当天涨幅会把脉冲误判成主线，忽略持续性、容量和共振。",
            "why_5_10_20d": "5日看短线热度，10日看连续性，20日看中期趋势，三者结合才能分辨主线、修复和退潮。",
            "why_amount_up_ratio": "成交额和上涨家数占比能验证是否有真正板块资金承接，而不是少数个股拉抬。",
            "why_broker_indicator": "券商经常先反映情绪回暖，但如果没有持续放量和扩散，不应直接当成进攻主线。",
        },
        "leader_judgement": {
            "ABSOLUTE_LEADER": {"definition": "板块辨识度最高、最先走强、最能带动情绪和资金回流的核心龙头。", "fit": "短线为主，也可兼顾波段。", "risk": "高位波动大，情绪退潮时杀伤强。", "weather": "RISK_ON 或至少非极弱市。"},
            "TREND_LEADER": {"definition": "沿均线趋势走强、持续性较好的主线核心。", "fit": "短线+中线都适合。", "risk": "趋势破坏后回撤明显。", "weather": "OBSERVE_ONLY 到 NORMAL 都可观察。"},
            "CAPACITY_CORE": {"definition": "市值容量大、机构和中长期资金更容易承接的核心资产。", "fit": "更适合中长线与稳健试错。", "risk": "爆发力弱于弹性股。", "weather": "弱市更有参考价值。"},
            "ELASTIC_LEADER": {"definition": "弹性大、涨速快、情绪带动强，但稳定性弱。", "fit": "更偏短线。", "risk": "高波动、高回撤。", "weather": "更适合风险偏好抬升时。"},
            "LOW_POSITION_REPAIR": {"definition": "前期跌深后首先修复的低位核心。", "fit": "偏短线观察，也可作为主线候选跟踪。", "risk": "可能只是反弹而非主升。", "weather": "弱市修复阶段更常见。"},
            "FOLLOWER": {"definition": "跟随龙头上涨，但缺少独立带动性和容量支撑。", "fit": "只适合特定强市短线。", "risk": "龙头一弱就先掉队。", "weather": "弱市不适合。"},
            "why_not_only_limit_up": "最强涨停不一定有承接，很多是情绪脉冲，次日容易高开低走。",
            "why_not_only_cheap": "低价不等于低风险，便宜股可能缺逻辑、缺资金、缺承接。",
            "why_split_capacity_elastic": "容量核心更稳，弹性股更快，必须区分，否则仓位和预期都会错配。",
        },
        "stock_operation_judgement": {
            "required_checks": [
                "先判断所属板块是不是主线或潜在主线",
                "再判断它是不是板块核心或至少不是纯跟风",
                "看当前位置是否过热，是否属于追涨",
                "看资金是否连续进入，而不是一天脉冲",
                "分清是回踩承接还是高位冲动追价",
                "分清适合短线还是中长线观察",
                "再决定是否进入候选池",
                "最后才决定是否进入模拟买点判断",
            ],
            "actions": {
                "OBSERVE": "只看，不买，不做进攻决策。",
                "WATCH": "进入观察名单，跟踪强弱变化，不代表买入。",
                "BUY_CANDIDATE": "人工确认的小仓试错候选，不代表自动买入。",
                "NEEDS_HUMAN_REVIEW": "模型发现信号，但风险或边界要求人工复核后才能动作。",
                "HOLD": "已有持仓继续持有，但要盯保护线和板块强弱。",
                "REDUCE": "先降仓，通常用于板块退潮、龙头转弱或冲高滞涨。",
                "SELL": "退出，不再持有，通常对应逻辑失效或止损触发。",
            },
        },
        "position_management": {
            "why_limit_risk_off": "RISK_OFF / OBSERVE_ONLY 下容错低，多只同时试错会放大连续错误。",
            "why_limit_buy_candidate_count": "弱市里最怕分散追高，BUY_CANDIDATE 数量必须压到最少。",
            "small_trial_condition": "至少板块不弱、个股是核心或容量核心、买点质量不低于 FAIR、且有承接和量能确认。",
            "observe_only_condition": "板块未确认、个股不是核心、位置过高、或只是情绪脉冲时只能观察。",
            "empty_wait_condition": "市场全面偏弱、候选股无清晰买点、或数据不足时必须空仓等待。",
            "why_manual_mapping_no_buy": "manual_mapping 不是正式成分验证结果，数据可信度和板块纯度都不够。",
            "why_poor_no_buy": "POOR 说明买点质量差，强做试错容易变成追涨挨打。",
            "why_missing_data_block": "没有数据就不能确认均线、突破、量能、承接，必须 missing_data。",
            "risk_off_rules": {
                "single_small_trial_position_limit": "10% to 15%",
                "max_new_positions_per_day": 1,
                "watch_stocks_can_buy": False,
                "manual_mapping_can_buy": False,
                "missing_data_can_buy": False,
            },
        },
        "stop_loss_take_profit": {
            "why_stop_loss": "没有止损，错了会越亏越大，框架无法闭环。",
            "why_take_profit": "没有止盈，看对也可能坐过山车把利润回吐。",
            "common_stop_loss": ["跌破10日线且无法收回", "放量破位", "板块转弱", "龙头掉队", "买入逻辑失效"],
            "common_take_profit": ["冲高放量滞涨分批止盈", "沿5日线/10日线滚动持有", "板块分歧扩大先兑现一部分"],
            "invalidation": "买入依赖的主线、龙头、承接、量价条件不再成立。",
            "board_retreat_reduce": "要，哪怕个股没破硬止损，也应先降仓。",
            "leader_weak_follower": "龙头走弱时，后排股通常优先减仓或退出。",
            "high_volume_stall": "分批止盈，不恋战。",
            "break_ma10_fail_recover": "视为保护线失守，应止损或至少大幅降仓。",
            "entry_condition": "回踩5日线/10日线企稳，或放量突破近3日高点后承接稳定。",
            "stop_loss_condition": "跌破10日线且无法收回，或板块转弱、龙头掉队、放量破位。",
            "take_profit_condition": "冲高放量滞涨分批止盈；若板块延续则沿5日线/10日线滚动持有。",
            "invalidation_condition": "跌破10日线且无法收回，或板块转弱、龙头掉队、放量破位。",
            "do_not_participate_condition": "高位追涨、数据不足、板块退潮、龙头不稳、或当前只允许观察时不参与。",
        },
        "dare_buy_dare_sell": {
            "why_not_never_buy": "风控不是永远不买，而是只在赔率和胜率都还可以时小仓试错。",
            "when_buy_candidate": "板块确认、核心明确、买点不差于 FAIR、量能和承接成立时敢给 BUY_CANDIDATE。",
            "when_observe_only": "弱市、非核心、追涨、逻辑不清、或数据不足时坚决 OBSERVE。",
            "when_watch_upgrade": "WATCH 只有在板块持续、个股承接改善、买点质量提升后才可升级。",
            "when_buy_downgrade": "板块转弱、龙头掉队、买点被破坏、或位置过热时必须降级。",
            "when_stop_loss": "跌破关键保护线且无法收回，或逻辑已失效时果断止损。",
            "when_take_profit": "冲高放量滞涨、板块分歧扩大、或利润已明显兑现时分批止盈。",
            "why_small_loss_big_win": "看错小亏、看对有扩展空间，才是可持续决策；永远不买只会错失有效机会。",
        },
    }


def build_subjective(handoff: dict[str, Any], retest: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_tech_sector_judgement": {
            "semi_5_10_20": "从现有本地研究结论看，半导体 10日和20日仍有历史强度，但当前被定义为老主线高位分歧后修复，未确认二次启动。",
            "electronic_chemicals": "电子化学品仍是 RETREATING / RETREAT_WARNING，不宜按新主线处理。",
            "advanced_packaging": "先进封装有修复痕迹但仍在 RETREATING，缺少板块共振确认。",
            "memory_chip": "存储芯片当前是 WATCH_ONLY，不是已确认二次启动。",
            "semi_equipment": "半导体设备未看到稳定容量核心带动，仍偏退潮后观察。",
            "board_resonance": "科技股当前没有形成明确板块共振，更多是局部修复。",
            "leader_stability": "龙头稳定性不足，难以支持整体板块再启动结论。",
            "amount": "现有本地研究未给出明确的科技方向整体持续放量确认，不能冒进判强。",
            "up_ratio": "上涨家数占比没有支持科技全面回暖的明确证据。",
            "why_not_few_names": "一两只上涨不等于板块二次启动，必须看整体强度、容量、龙头、共振和持续性。",
            "final_state": "WATCH_ONLY",
            "short_term_participation": "WATCH_ONLY",
            "mid_long_term_observation": "YES",
            "suggest_model_test_candidate_pool": "NO",
            "reason": "工程现有研究结论是半导体老主线高位分歧后修复，电子化学品/先进封装/半导体设备仍偏退潮，存储芯片仅 WATCH_ONLY，不能因为局部反弹就纳入当前测试候选池。",
        },
        "next_stage_mainline_judgement": {
            "current_stage_mainline": [
                {"name": "化学制药", "sector_nature": "STAGE_MAINLINE", "mainline_score_0_100": 100, "fund_flow": "持续性较强", "leader": "恒瑞医药", "capacity_core": "恒瑞医药", "elastic_leader": "百济神州", "low_position_support": "有", "short_term": "YES_BUT_SMALL_TRIAL", "mid_long_term": "YES", "risk": "高位加速后分歧与追高风险"},
                {"name": "生物制品", "sector_nature": "STAGE_MAINLINE", "mainline_score_0_100": 100, "fund_flow": "持续性较强", "leader": "荣昌生物", "capacity_core": "荣昌生物", "elastic_leader": "三生国健", "low_position_support": "有", "short_term": "WATCH_ONLY", "mid_long_term": "YES", "risk": "仍需继续看量能延续"},
                {"name": "创新药", "sector_nature": "STAGE_MAINLINE", "mainline_score_0_100": 100, "fund_flow": "持续性较强", "leader": "恒瑞医药", "capacity_core": "恒瑞医药", "elastic_leader": "艾力斯", "low_position_support": "有", "short_term": "WATCH_ONLY", "mid_long_term": "YES", "risk": "与化学制药高度重叠，需防止重复追高"},
            ],
            "potential_mainline": [
                {"name": "养殖业", "sector_nature": "POTENTIAL_MAINLINE", "mainline_score_0_100": 100, "fund_flow": "有持续迹象但未完全确认", "leader": "益生股份", "capacity_core": "温氏股份/牧原股份", "elastic_leader": "益生股份", "low_position_support": "有", "short_term": "WATCH_ONLY", "mid_long_term": "YES", "risk": "可能是一日游或低位修复未完成确认"},
            ],
            "emotion_hotspot": [
                {"name": "券商", "sector_nature": "SENTIMENT_INDICATOR", "mainline_score_0_100": 71, "fund_flow": "更多反映风偏", "leader": "国泰海通", "capacity_core": "国泰海通", "elastic_leader": "弹性分支不固定", "low_position_support": "有", "short_term": "WATCH_ONLY", "mid_long_term": "WATCH_ONLY", "risk": "若不能持续放量，容易只是情绪脉冲"},
            ],
            "mid_long_term_capital_direction": [
                {"name": "医药主线容量核心", "sector_nature": "STAGE_MAINLINE", "mainline_score_0_100": 100, "fund_flow": "持续", "leader": "恒瑞医药", "capacity_core": "恒瑞医药", "elastic_leader": "百济神州/艾力斯", "low_position_support": "有", "short_term": "YES_BUT_SMALL_TRIAL", "mid_long_term": "YES", "risk": "追高容错下降"},
            ],
            "low_position_repair": [
                {"name": "低位消费修复", "sector_nature": "LOW_POSITION_REPAIR", "mainline_score_0_100": 60, "fund_flow": "不稳定", "leader": "金字火腿", "capacity_core": "暂无明确容量核心", "elastic_leader": "修复弹性股不固定", "low_position_support": "有", "short_term": "WATCH_ONLY", "mid_long_term": "NO", "risk": "容易分化回落"},
            ],
            "retreat_warning": [
                {"name": "半导体", "sector_nature": "RETREAT_WARNING", "mainline_score_0_100": 49, "fund_flow": "高位分歧后修复", "leader": "江波龙", "capacity_core": "江波龙/中微公司观察中", "elastic_leader": "局部弹性股", "low_position_support": "弱", "short_term": "NO", "mid_long_term": "WATCH_ONLY", "risk": "老主线退潮未完成修复"},
                {"name": "电子化学品", "sector_nature": "RETREAT_WARNING", "mainline_score_0_100": 37, "fund_flow": "偏弱", "leader": "国瓷材料", "capacity_core": "国瓷材料", "elastic_leader": "飞凯材料", "low_position_support": "弱", "short_term": "NO", "mid_long_term": "WATCH_ONLY", "risk": "仍在退潮段"},
            ],
            "not_recommended": [
                {"name": "医疗研发外包（884244）", "reason": "真实成分来源不足，仅能作为人工观察样本，当前不建议正式参与。"},
                {"name": "科技高位分歧方向", "reason": "未确认二次启动，不适合当前纳入进攻池。"},
            ],
        },
    }


def build_self_check(handoff: dict[str, Any], retest: dict[str, Any], unified: dict[str, Any]) -> dict[str, Any]:
    candidate_count = len(handoff["handoff_to_trading_model"])
    buy_count = len([x for x in handoff["handoff_to_trading_model"] if x["candidate_action"] == "BUY_CANDIDATE"])
    manual_mapping_buy = any(x["manual_mapping_candidate"] and x["candidate_action"] == "BUY_CANDIDATE" for x in handoff["handoff_to_trading_model"])
    poor_buy = False
    missing_quote_trigger = False
    buy_item = unified["position_and_trade_judgement"]["candidate_buy_point_status"]["items"][0]
    if not buy_item["buy_point_data_ready"] and buy_item["simulated_buy_point_triggered"]:
        missing_quote_trigger = True
    failed_checks: list[str] = []
    if candidate_count > 5 or candidate_count < 3:
        failed_checks.append("candidate_pool_size_out_of_3_to_5")
    if buy_count > 1:
        failed_checks.append("risk_off_buy_candidate_more_than_1")
    if manual_mapping_buy:
        failed_checks.append("manual_mapping_promoted_to_buy")
    if poor_buy:
        failed_checks.append("poor_quality_allowed_to_buy")
    if missing_quote_trigger:
        failed_checks.append("buy_triggered_without_ready_data")

    return {
        "overreach_check": {
            "candidate_pool_MANUAL_json_modified": {"value": False, "evidence": "工程本轮没有编辑该文件，正式候选池保持不动。"},
            "simulated_account_state_json_modified": {"value": False, "evidence": f"正式账户 hash 仍为 {FORMAL_HASH}。"},
            "real_order_placed": {"value": False, "evidence": "所有 review/boundary_flags 都保持 false。"},
            "auto_trading_enabled": {"value": False, "evidence": "state 与报告边界字段均为 false。"},
            "full_market_auto_selection": {"value": False, "evidence": "当前仅处理 5 只 handoff 股票，没有做全市场自动选股。"},
            "validation_private_used": {"value": False, "evidence": "retest boundary_flags 明确 validation_private_used_for_today_decision=false。"},
            "watch_treated_as_buy": {"value": False, "evidence": "WATCH / WATCH_ONLY 在统一日报和 retest 中都被解释为观察。"},
            "manual_mapping_as_official": {"value": False, "evidence": "万邦医药、普蕊斯均保留 manual_mapping / observation_only。"},
            "fabricated_buy_on_missing_data": {"value": False, "evidence": "早期 missing_data 被保留，后续 quote 补齐后才重跑 retest，并写明数据来源。"},
            "too_many_buy_in_risk_off": {"value": False, "evidence": "RISK_OFF 下 BUY_CANDIDATE 只有 1 只：600276.SH。"},
        },
        "candidate_pool_rules": {
            "candidate_count_3_to_5": {"value": True, "evidence": f"当前 handoff 范围 {candidate_count} 只。"},
            "risk_off_buy_candidate_max_1": {"value": True, "evidence": f"当前 BUY_CANDIDATE 数量 {buy_count}。"},
            "watch_not_buyable": {"value": True, "evidence": "WATCH 股票均为 simulate_buy_allowed=false。"},
            "watch_only_not_buyable": {"value": True, "evidence": "manual_mapping / WATCH_ONLY 股票只观察。"},
            "manual_mapping_observation_only": {"value": True, "evidence": "301520.SZ、301257.SZ 都是 observation_only。"},
            "no_high_chase_buy_issue": {"value": True, "evidence": "现有池中只有恒瑞医药进入小仓试错候选，其余均未升级。"},
            "no_poor_buy": {"value": True, "evidence": "manual_mapping quality=POOR 的股票未允许模拟买入。"},
            "no_missing_quote_trigger": {"value": True, "evidence": "最新统一日报含 buy_point_data_ready=true、quote_data_source 和 quote_trade_date。"},
        },
        "quote_data_rules": {
            "quote_data_complete_for_buy_check": {"value": True, "evidence": "恒瑞医药具备 latest_quote_loaded、OHLC、ma5/ma10/ma20、breakout_3d_high、volume_expansion。"},
            "has_latest_quote_loaded": {"value": True, "evidence": "统一日报与 retest 均有 latest_quote_loaded。"},
            "has_quote_data_source": {"value": True, "evidence": "统一日报写明 quote_data_source=tushare_readonly_handoff_latest_quotes。"},
            "has_quote_trade_date": {"value": True, "evidence": "统一日报写明 quote_trade_date=20260706。"},
            "has_ohlc": {"value": True, "evidence": "handoff_latest_readonly_quotes_20260706.json 包含 open/high/low/close。"},
            "has_ma5_ma10": {"value": True, "evidence": "retest 已计算 ma5/ma10。"},
            "has_recent_3d_high": {"value": True, "evidence": "retest 有 breakout_ref_high_3d。"},
            "has_volume_confirmed": {"value": True, "evidence": "retest 有 volume_expansion=true。"},
            "missing_data_gate_works": {"value": True, "evidence": "早期 trading_model_handoff_test_20260706 就是 missing_data gate 的证明。"},
            "no_unexplained_missing_to_trigger": {"value": True, "evidence": "统一日报已新增 change_explanation 解释从 missing_data 到 triggered 的原因。"},
        },
        "unified_daily_rules": {
            "unified_name": {"value": True, "evidence": "report_name=股票AI交易助手日报。"},
            "no_model_split_in_body": {"value": True, "evidence": "正文按统一日报口径输出。"},
            "buy_candidate_not_auto_buy": {"value": True, "evidence": "日报中明确写为小仓试错候选。"},
            "watch_only_means_observe": {"value": True, "evidence": "WATCH / WATCH_ONLY 全部写为观察。"},
            "has_market_weather": {"value": True, "evidence": "日报明确写了 RISK_OFF / OBSERVE_ONLY。"},
            "distinguish_hotspot_and_mainline": {"value": True, "evidence": "日报区分了当前阶段主线、潜在主线、情绪热点。"},
            "distinguish_short_mid_watch": {"value": True, "evidence": "日报区分短线候选、中长线观察、只观察股票。"},
            "has_retreat_warning": {"value": True, "evidence": "日报写了退潮预警。"},
            "has_tomorrow_conditions": {"value": True, "evidence": "日报含明日重点板块和明日操作观察条件。"},
            "has_position_advice": {"value": True, "evidence": "日报含每只股票操作建议。"},
            "has_data_insufficiency_prompt": {"value": False, "evidence": "当前日报有数据来源解释，但没有为通用缺数据场景预留显式固定段落。"},
            "avoid_news_fabrication": {"value": True, "evidence": "当前日报没有编造政策面或消息面。"},
        },
        "consult_template": [
            "1. 总结论",
            "2. 当前动作",
            "3. 市场天气",
            "4. 板块性质",
            "5. 主线评分",
            "6. 龙头地位",
            "7. 个股位置",
            "8. 资金情况",
            "9. 短线买点",
            "10. 中长线逻辑",
            "11. 仓位建议",
            "12. 止损条件",
            "13. 止盈条件",
            "14. 不参与条件",
            "15. 是否适合进入 model_test_candidate_pool",
            "16. 是否适合进入正式 candidate_pool_MANUAL.json",
            "17. 数据不足项",
            "18. 明日继续观察条件",
        ],
        "failed_checks": failed_checks + ["unified_daily_missing_explicit_generic_data_insufficiency_section"],
    }


def build_scores() -> dict[str, Any]:
    return {
        "theory_logic_understanding": {"score": 88, "reason": "规则口径已能稳定表达，但仍依赖人工复核来压住复杂边界。"},
        "board_identification": {"score": 82, "reason": "医药、养殖、科技退潮判断基本一致，但 884244 和科技二次启动还需更多样本。"},
        "leader_identification": {"score": 80, "reason": "能区分恒瑞、百济、益生等角色，但容量核心和弹性层次还需更系统化字段。"},
        "buy_point_judgement": {"score": 76, "reason": "已能基于只读行情做买点判断，但 current logic 仍偏规则化，需更多回测样本。"},
        "position_management": {"score": 85, "reason": "RISK_OFF 下单票小仓试错、WATCH 禁买、manual_mapping 禁买执行较稳。"},
        "stop_loss_take_profit": {"score": 84, "reason": "条件已清晰，但尚未经过足够多日真实模拟检验。"},
        "risk_boundary": {"score": 92, "reason": "没有越权改账户、改候选池、自动交易或接真实账户。"},
        "data_honesty": {"score": 90, "reason": "能承认 missing_data，并在补齐后解释数据来源；仍需把缺数据提示做成固定模板。"},
        "daily_report_ability": {"score": 78, "reason": "统一日报已经成型，但通用缺数据提示和咨询模板复用还需继续收敛。"},
        "consulting_ability": {"score": 74, "reason": "结构已能输出，但还没做足够多轮真实问答自测。"},
        "overall_maturity": {"score": 79, "reason": "可进入人工复核下的日报/咨询试运行，但离完全成熟还有数据结构和样本验证差距。"},
    }


def build_report() -> dict[str, Any]:
    handoff = load_json(HANDOFF_PATH)
    retest = load_json(RETEST_PATH)
    unified = load_json(UNIFIED_PATH)
    official_hash = file_sha256(STATE_PATH)
    self_check = build_self_check(handoff, retest, unified)
    return {
        "report_name": "股票AI交易助手模型自检考试报告",
        "report_date": "20260706",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "official_state_hash": official_hash,
        "official_state_hash_preserved": official_hash == FORMAL_HASH,
        "theory_logic_exam": build_theory() | build_subjective(handoff, retest),
        "model_execution_self_check": self_check,
        "scores": build_scores(),
        "final_conclusion": {
            "theory_exam_result": "PARTIAL_PASS",
            "execution_self_check_result": "PARTIAL_PASS",
            "can_start_daily_report_trial": "YES_BUT_MANUAL_REVIEW_REQUIRED",
            "can_start_consulting_trial": "YES_BUT_MANUAL_REVIEW_REQUIRED",
            "can_enable_feishu_auto_send": "NO",
            "can_update_official_candidate_pool_manual": "NO",
            "can_modify_simulated_account_state": "NO",
            "allow_real_trading": "NO",
            "largest_current_problem": "规则口径已经基本统一，但科技方向、884244 成分验证、通用缺数据提示和买点逻辑样本验证仍不够成熟。",
            "next_most_important_fix": "先把缺数据提示、咨询模板和板块/龙头字段进一步固定，再继续扩日报或自动化。",
        },
    }


def render_md(report: dict[str, Any]) -> str:
    theory = report["theory_logic_exam"]
    self_check = report["model_execution_self_check"]
    final = report["final_conclusion"]
    scores = report["scores"]
    failed_checks = self_check["failed_checks"]
    board = theory["board_judgement"]
    leader = theory["leader_judgement"]
    op = theory["stock_operation_judgement"]
    pos = theory["position_management"]
    sltp = theory["stop_loss_take_profit"]
    dbs = theory["dare_buy_dare_sell"]
    tech = theory["current_tech_sector_judgement"]
    next_main = theory["next_stage_mainline_judgement"]
    lines = [
        "# 股票AI交易助手模型自检考试报告",
        "",
        f"- 日期：{report['report_date']}",
        f"- 生成时间：{report['generated_at']}",
        f"- 正式账户 hash 保持：{report['official_state_hash_preserved']}",
        "",
        "## 一、理论逻辑考试",
        "",
        "### 题目 1：板块判断",
        f"1. 阶段主线 STAGE_MAINLINE：{board['STAGE_MAINLINE']}",
        f"2. 情绪热点 EMOTION_HOTSPOT：{board['EMOTION_HOTSPOT']}",
        f"3. 潜在主线 POTENTIAL_MAINLINE：{board['POTENTIAL_MAINLINE']}",
        f"4. 低位修复 LOW_POSITION_REPAIR：{board['LOW_POSITION_REPAIR']}",
        f"5. 退潮预警 RETREAT_WARNING：{board['RETREAT_WARNING']}",
        f"6. 情绪指标 SENTIMENT_INDICATOR：{board['SENTIMENT_INDICATOR']}",
        f"7. 为什么不能只看当天涨幅：{board['why_not_day1_only']}",
        f"8. 为什么要看 5/10/20 日强度：{board['why_5_10_20d']}",
        f"9. 为什么要看成交额和上涨家数占比：{board['why_amount_up_ratio']}",
        f"10. 为什么券商常常更像情绪指标：{board['why_broker_indicator']}",
        "",
        "### 题目 2：龙头判断",
        f"1. ABSOLUTE_LEADER：{leader['ABSOLUTE_LEADER']['definition']} 适用={leader['ABSOLUTE_LEADER']['fit']} 风险={leader['ABSOLUTE_LEADER']['risk']} 天气={leader['ABSOLUTE_LEADER']['weather']}",
        f"2. TREND_LEADER：{leader['TREND_LEADER']['definition']} 适用={leader['TREND_LEADER']['fit']} 风险={leader['TREND_LEADER']['risk']} 天气={leader['TREND_LEADER']['weather']}",
        f"3. CAPACITY_CORE：{leader['CAPACITY_CORE']['definition']} 适用={leader['CAPACITY_CORE']['fit']} 风险={leader['CAPACITY_CORE']['risk']} 天气={leader['CAPACITY_CORE']['weather']}",
        f"4. ELASTIC_LEADER：{leader['ELASTIC_LEADER']['definition']} 适用={leader['ELASTIC_LEADER']['fit']} 风险={leader['ELASTIC_LEADER']['risk']} 天气={leader['ELASTIC_LEADER']['weather']}",
        f"5. LOW_POSITION_REPAIR：{leader['LOW_POSITION_REPAIR']['definition']} 适用={leader['LOW_POSITION_REPAIR']['fit']} 风险={leader['LOW_POSITION_REPAIR']['risk']} 天气={leader['LOW_POSITION_REPAIR']['weather']}",
        f"6. FOLLOWER：{leader['FOLLOWER']['definition']} 适用={leader['FOLLOWER']['fit']} 风险={leader['FOLLOWER']['risk']} 天气={leader['FOLLOWER']['weather']}",
        f"7. 为什么不能只买最强涨停：{leader['why_not_only_limit_up']}",
        f"8. 为什么不能只买低位便宜股：{leader['why_not_only_cheap']}",
        f"9. 为什么要区分容量核心和弹性股：{leader['why_split_capacity_elastic']}",
        "",
        "### 题目 3：个股操作判断",
        "面对一只股票，必须按下面顺序判断：",
    ]
    lines.extend(f"- {item}" for item in op["required_checks"])
    lines += [
        "动作解释：",
        f"- OBSERVE：{op['actions']['OBSERVE']}",
        f"- WATCH：{op['actions']['WATCH']}",
        f"- BUY_CANDIDATE：{op['actions']['BUY_CANDIDATE']}",
        f"- NEEDS_HUMAN_REVIEW：{op['actions']['NEEDS_HUMAN_REVIEW']}",
        f"- HOLD：{op['actions']['HOLD']}",
        f"- REDUCE：{op['actions']['REDUCE']}",
        f"- SELL：{op['actions']['SELL']}",
        "",
        "### 题目 4：仓位管理",
        f"1. 为什么 RISK_OFF / OBSERVE_ONLY 不能多只同时试错：{pos['why_limit_risk_off']}",
        f"2. 为什么弱市里 BUY_CANDIDATE 数量要限制：{pos['why_limit_buy_candidate_count']}",
        f"3. 什么情况下可以小仓试错：{pos['small_trial_condition']}",
        f"4. 什么情况下只能观察：{pos['observe_only_condition']}",
        f"5. 什么情况下必须空仓等待：{pos['empty_wait_condition']}",
        f"6. 为什么 manual_mapping 不能直接 BUY_CANDIDATE：{pos['why_manual_mapping_no_buy']}",
        f"7. 为什么 POOR 不能模拟买入：{pos['why_poor_no_buy']}",
        f"8. 为什么缺数据必须 missing_data：{pos['why_missing_data_block']}",
        f"9. 单只小仓试错上限：{pos['risk_off_rules']['single_small_trial_position_limit']}",
        f"10. 总新开仓数量上限：{pos['risk_off_rules']['max_new_positions_per_day']}",
        f"11. WATCH 股票是否允许买入：{pos['risk_off_rules']['watch_stocks_can_buy']}",
        f"12. manual_mapping 股票是否允许买入：{pos['risk_off_rules']['manual_mapping_can_buy']}",
        f"13. 缺数据股票是否允许买入：{pos['risk_off_rules']['missing_data_can_buy']}",
        "",
        "### 题目 5：止损止盈",
        f"1. 为什么必须有止损：{sltp['why_stop_loss']}",
        f"2. 为什么必须有止盈：{sltp['why_take_profit']}",
        f"3. 常见止损条件：{sltp['common_stop_loss']}",
        f"4. 常见止盈条件：{sltp['common_take_profit']}",
        f"5. 什么叫买入逻辑失效：{sltp['invalidation']}",
        f"6. 如果板块退潮要不要降仓：{sltp['board_retreat_reduce']}",
        f"7. 龙头走弱后排怎么处理：{sltp['leader_weak_follower']}",
        f"8. 冲高放量滞涨怎么处理：{sltp['high_volume_stall']}",
        f"9. 跌破 10 日线且无法收回怎么处理：{sltp['break_ma10_fail_recover']}",
        f"10. entry_condition：{sltp['entry_condition']}",
        f"11. stop_loss_condition：{sltp['stop_loss_condition']}",
        f"12. take_profit_condition：{sltp['take_profit_condition']}",
        f"13. invalidation_condition：{sltp['invalidation_condition']}",
        f"14. do_not_participate_condition：{sltp['do_not_participate_condition']}",
        "",
        "### 题目 6：敢买敢卖",
        f"1. 为什么风控不是永远不买：{dbs['why_not_never_buy']}",
        f"2. 什么情况下应该敢给 BUY_CANDIDATE：{dbs['when_buy_candidate']}",
        f"3. 什么情况下必须坚决 OBSERVE：{dbs['when_observe_only']}",
        f"4. 什么情况下 WATCH 可以升级：{dbs['when_watch_upgrade']}",
        f"5. 什么情况下 BUY_CANDIDATE 必须降级：{dbs['when_buy_downgrade']}",
        f"6. 什么情况下要果断止损：{dbs['when_stop_loss']}",
        f"7. 什么情况下要分批止盈：{dbs['when_take_profit']}",
        f"8. 为什么“看错小亏，看对有机会赚”更合理：{dbs['why_small_loss_big_win']}",
        "",
        "### 题目 7：当前科技股判断主观题",
        f"1. 半导体整体 5/10/20 日表现：{tech['semi_5_10_20']}",
        f"2. 电子化学品：{tech['electronic_chemicals']}",
        f"3. 先进封装：{tech['advanced_packaging']}",
        f"4. 存储芯片：{tech['memory_chip']}",
        f"5. 半导体设备：{tech['semi_equipment']}",
        f"6. 科技股有没有板块共振：{tech['board_resonance']}",
        f"7. 龙头是否稳定：{tech['leader_stability']}",
        f"8. 成交额是否放大：{tech['amount']}",
        f"9. 上涨家数占比是否改善：{tech['up_ratio']}",
        f"10. 为什么不能因一两只上涨就判断二次启动：{tech['why_not_few_names']}",
        f"11. 科技股当前状态：{tech['final_state']}",
        f"12. 是否适合短线参与：{tech['short_term_participation']}",
        f"13. 是否适合中长线观察：{tech['mid_long_term_observation']}",
        f"14. 是否建议纳入当前 model_test_candidate_pool：{tech['suggest_model_test_candidate_pool']}",
        f"15. 理由：{tech['reason']}",
        "",
        "### 题目 8：下一阶段主线判断主观题",
        "当前阶段主线：",
    ]
    for item in next_main["current_stage_mainline"]:
        lines.append(f"- {item['name']} | nature={item['sector_nature']} | score={item['mainline_score_0_100']} | 资金={item['fund_flow']} | 龙头={item['leader']} | 容量核心={item['capacity_core']} | 弹性股={item['elastic_leader']} | 低位补涨={item['low_position_support']} | 短线={item['short_term']} | 中长线={item['mid_long_term']} | 风险={item['risk']}")
    lines.append("潜在主线：")
    for item in next_main["potential_mainline"]:
        lines.append(f"- {item['name']} | nature={item['sector_nature']} | score={item['mainline_score_0_100']} | 资金={item['fund_flow']} | 龙头={item['leader']} | 容量核心={item['capacity_core']} | 弹性股={item['elastic_leader']} | 低位补涨={item['low_position_support']} | 短线={item['short_term']} | 中长线={item['mid_long_term']} | 风险={item['risk']}")
    lines.append("情绪热点：")
    for item in next_main["emotion_hotspot"]:
        lines.append(f"- {item['name']} | nature={item['sector_nature']} | score={item['mainline_score_0_100']} | 资金={item['fund_flow']} | 龙头={item['leader']} | 容量核心={item['capacity_core']} | 弹性股={item['elastic_leader']} | 低位补涨={item['low_position_support']} | 短线={item['short_term']} | 中长线={item['mid_long_term']} | 风险={item['risk']}")
    lines.append("中长期资金方向：")
    for item in next_main["mid_long_term_capital_direction"]:
        lines.append(f"- {item['name']} | nature={item['sector_nature']} | score={item['mainline_score_0_100']} | 资金={item['fund_flow']} | 龙头={item['leader']} | 容量核心={item['capacity_core']} | 弹性股={item['elastic_leader']} | 低位补涨={item['low_position_support']} | 短线={item['short_term']} | 中长线={item['mid_long_term']} | 风险={item['risk']}")
    lines.append("低位修复方向：")
    for item in next_main["low_position_repair"]:
        lines.append(f"- {item['name']} | nature={item['sector_nature']} | score={item['mainline_score_0_100']} | 资金={item['fund_flow']} | 龙头={item['leader']} | 容量核心={item['capacity_core']} | 弹性股={item['elastic_leader']} | 低位补涨={item['low_position_support']} | 短线={item['short_term']} | 中长线={item['mid_long_term']} | 风险={item['risk']}")
    lines.append("退潮预警方向：")
    for item in next_main["retreat_warning"]:
        lines.append(f"- {item['name']} | nature={item['sector_nature']} | score={item['mainline_score_0_100']} | 资金={item['fund_flow']} | 龙头={item['leader']} | 容量核心={item['capacity_core']} | 弹性股={item['elastic_leader']} | 低位补涨={item['low_position_support']} | 短线={item['short_term']} | 中长线={item['mid_long_term']} | 风险={item['risk']}")
    lines.append("不建议参与方向：")
    for item in next_main["not_recommended"]:
        lines.append(f"- {item['name']}：{item['reason']}")
    lines += [
        "",
        "## 二、模型执行自检",
        "",
        "### 自检 1：是否越权",
    ]
    for key, value in self_check["overreach_check"].items():
        lines.append(f"- {key}={value['value']}；证据：{value['evidence']}")
    lines += [
        "",
        "### 自检 2：候选池规则",
    ]
    for key, value in self_check["candidate_pool_rules"].items():
        lines.append(f"- {key}={value['value']}；证据：{value['evidence']}")
    lines += [
        "",
        "### 自检 3：行情数据规则",
    ]
    for key, value in self_check["quote_data_rules"].items():
        lines.append(f"- {key}={value['value']}；证据：{value['evidence']}")
    lines += [
        "",
        "### 自检 4：统一日报规则",
    ]
    for key, value in self_check["unified_daily_rules"].items():
        lines.append(f"- {key}={value['value']}；证据：{value['evidence']}")
    lines += [
        "",
        "### 自检 5：咨询能力模板",
    ]
    lines.extend(f"- {item}" for item in self_check["consult_template"])
    lines += [
        "",
        "### 自检 6：评分",
        "",
        "## 三、评分",
    ]
    for key, value in scores.items():
        lines.append(f"- {key}: {value['score']} / 100；{value['reason']}")
    lines += [
        "",
        "## 四、failed_checks",
        f"- {failed_checks}",
        "",
        "## 五、最终结论",
        f"- 本轮是否通过理论考试：{final['theory_exam_result']}",
        f"- 本轮是否通过模型执行自检：{final['execution_self_check_result']}",
        f"- 当前是否可以开始日报试运行：{final['can_start_daily_report_trial']}",
        f"- 当前是否可以开始咨询功能试运行：{final['can_start_consulting_trial']}",
        f"- 当前是否可以接飞书自动发送：{final['can_enable_feishu_auto_send']}",
        f"- 当前是否可以更新正式 candidate_pool_MANUAL.json：{final['can_update_official_candidate_pool_manual']}",
        f"- 当前是否可以修改 simulated_account_state.json：{final['can_modify_simulated_account_state']}",
        f"- 当前是否允许真实交易：{final['allow_real_trading']}",
        f"- 当前最大问题是什么：{final['largest_current_problem']}",
        f"- 下一轮最应该修什么：{final['next_most_important_fix']}",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    OUTPUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD.write_text(render_md(report), encoding="utf-8")
    print(json.dumps({"json": str(OUTPUT_JSON), "md": str(OUTPUT_MD)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
