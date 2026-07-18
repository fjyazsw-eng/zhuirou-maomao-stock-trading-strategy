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
OUTPUT_JSON_PATH = REVIEW_DIR / "unified_stock_ai_daily_report_20260706.json"
OUTPUT_MD_PATH = REVIEW_DIR / "unified_stock_ai_daily_report_20260706.md"
FORMAL_HASH = "2D545CDEC06244FEE96928207736D6A99964057413A34FBF9E3FD45465749454"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest().upper()


def make_market_summary(handoff: dict[str, Any]) -> dict[str, Any]:
    weather = handoff["market_weather"]
    rows = handoff["handoff_to_trading_model"]
    short_term_candidates = []
    mid_long_watch = []
    watch_only = []
    for row in rows:
        action = row["candidate_action"]
        item = {
            "ts_code": row["ts_code"],
            "name": row["name"],
            "sector": row["sector"],
            "summary": row["short_term_logic"],
            "module_source": "market_and_selection",
        }
        if action == "BUY_CANDIDATE":
            short_term_candidates.append(
                {
                    **item,
                    "label": "小仓试错候选",
                    "note": "仅代表可进入人工确认级别的小仓试错候选，不代表自动买入。",
                }
            )
        elif row["sector_nature"] in {"STAGE_MAINLINE", "POTENTIAL_MAINLINE"}:
            mid_long_watch.append(
                {
                    **item,
                    "label": "中长线观察",
                    "note": row["mid_long_term_logic"],
                }
            )
        else:
            watch_only.append(
                {
                    **item,
                    "label": "只观察",
                    "note": "当前仅观察，不进入买入判断。",
                }
            )

    return {
        "market_weather": {
            "value": f"{weather['market_risk_level']} / {weather['attack_level']}",
            "summary": "当前市场偏谨慎，不适合全面进攻。" if weather["market_risk_level"] == "RISK_OFF" else "市场允许继续观察结构机会。",
            "module_source": "market_and_selection",
        },
        "current_stage_mainlines": [
            {
                "name": "化学制药",
                "evidence": "恒瑞医药、百济神州仍在主线观察名单内。",
                "module_source": "market_and_selection",
            }
        ],
        "potential_mainlines": [
            {
                "name": "养殖业",
                "evidence": "益生股份维持观察，但仍需验证持续性和市场共振。",
                "module_source": "market_and_selection",
            }
        ],
        "emotion_hotspots": [
            {
                "name": "医药修复",
                "evidence": "医药方向仍是当前最清晰的观察中心，但节奏偏谨慎。",
                "module_source": "market_and_selection",
            }
        ],
        "mid_long_term_capital_directions": [
            {
                "name": "医药主线容量核心",
                "evidence": "20日趋势与容量核心持续性仍是中长期资金观察重点。",
                "module_source": "market_and_selection",
            }
        ],
        "retreat_warnings": [
            {
                "name": "高位追涨风险",
                "evidence": "RISK_OFF 环境下追高容错低，若量价背离或板块分歧扩大，要及时降温。",
                "module_source": "market_and_selection",
            }
        ],
        "short_term_candidate_stocks": short_term_candidates,
        "mid_long_term_watch_stocks": mid_long_watch,
        "watch_only_stocks": watch_only,
        "tomorrow_sector_watch_conditions": [
            {
                "name": "化学制药",
                "condition": "看核心股是否继续维持 5/10 日线承接，且量能不明显转弱。",
                "module_source": "market_and_selection",
            },
            {
                "name": "养殖业",
                "condition": "看持续性是否延续，而不是快速退回低位轮动。",
                "module_source": "market_and_selection",
            },
            {
                "name": "医疗研发外包",
                "condition": "数据样本仍偏人工观察，先看强弱变化，不做进攻结论。",
                "module_source": "market_and_selection",
            },
        ],
    }


def make_position_and_trade_summary(retest: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    hengrui = retest["buy_judgement_for_hengrui"]
    quote_file_used = retest["handoff_read_result"]["quotes_file"]
    quote_trade_date = retest["actual_trade_date_used"]
    quote_data_source = "tushare_readonly_handoff_latest_quotes"
    buy_point_data_ready = bool(hengrui["latest_quote_loaded"])
    simulated_buy_point_triggered = bool(buy_point_data_ready and hengrui["simulated_buy_point_triggered"])
    buy_point_summary = (
        "600276.SH 已基于补齐后的交易侧 readonly quote 进入人工确认级别的小仓试错候选；其余股票仅观察。"
        if buy_point_data_ready
        else "行情数据不足，暂不判断买点。"
    )
    change_explanation = (
        "上一版 trading_model_handoff_test_20260706 使用的是未补齐 5 只交接股票行情的 market_data_20260706.json，所以是 missing_data。"
        " 这版统一日报引用的是后续补齐后的 handoff_latest_readonly_quotes_20260706.json，并与 trading_model_handoff_retest_20260706 保持一致。"
        if buy_point_data_ready
        else "当前未补齐到可靠交易侧行情，因此维持 missing_data。"
    )
    other_watch = [retest["watch_review_for_wanbang"], *retest["watch_review_for_other_stocks"]]
    operation_advice = [
        {
            "ts_code": "600276.SH",
            "name": "恒瑞医药",
            "advice": "进入人工确认观察。若人工确认通过，可作为小仓试错候选；当前不执行自动买入。",
            "buy_point_condition": "回踩 5 日线/10 日线企稳，或放量突破近 3 日高点后承接稳定。",
            "stop_loss_condition": hengrui["stop_loss_condition"],
            "take_profit_condition": hengrui["take_profit_condition"],
            "do_not_participate_condition": "若行情承接转弱、跌破关键均线且无法收回，或板块转弱，则不参与。",
            "next_day_watch_condition": "继续看 5/10 日线承接、量能和突破后是否稳住。",
            "module_source": "position_and_trade_judgement",
        }
    ]
    for row in other_watch:
        operation_advice.append(
            {
                "ts_code": row["ts_code"],
                "name": row["name"],
                "advice": "继续观察，不做买入。",
                "buy_point_condition": "当前仅观察，不输出买点建议。",
                "stop_loss_condition": row["downgrade_condition"],
                "take_profit_condition": "当前无持仓，不设置止盈执行。",
                "do_not_participate_condition": "当前属于 WATCH / WATCH_ONLY，只观察不参与买入。",
                "next_day_watch_condition": row["upgrade_watch_condition"],
                "module_source": "position_and_trade_judgement",
            }
        )

    return {
        "current_simulated_positions": {
            "cash": state["cash"],
            "total_equity": state["total_equity"],
            "positions": state["positions"],
            "summary": "当前为空仓，现金 20000，总资产 20000。",
            "module_source": "position_and_trade_judgement",
        },
        "candidate_buy_point_status": {
            "summary": buy_point_summary,
            "items": [
                {
                    "ts_code": "600276.SH",
                    "name": "恒瑞医药",
                    "quote_data_source": quote_data_source,
                    "quote_trade_date": quote_trade_date,
                    "latest_quote_loaded": hengrui["latest_quote_loaded"],
                    "buy_point_data_ready": buy_point_data_ready,
                    "buy_point_judgement_source": "trading_model_handoff_retest_20260706",
                    "latest_price": hengrui["latest_price"],
                    "buy_point_quality": hengrui["buy_point_quality"],
                    "review_status": hengrui["review_status"] if buy_point_data_ready else "missing_data",
                    "simulated_buy_point_triggered": simulated_buy_point_triggered,
                    "manual_confirmation_required": True,
                    "no_auto_buy": True,
                    "position_limit": "small_trial_only",
                    "quote_file_used": quote_file_used,
                    "change_explanation": change_explanation,
                    "module_source": "position_and_trade_judgement",
                }
            ],
        },
        "watch_stock_upgrade_or_downgrade": [
            {
                "ts_code": row["ts_code"],
                "name": row["name"],
                "status": row["review_status"],
                "observation_only": True,
                "summary": row["conclusion"],
                "module_source": "position_and_trade_judgement",
            }
            for row in other_watch
        ],
        "operation_advice_by_stock": operation_advice,
        "tomorrow_operation_watch_conditions": [
            {
                "name": "恒瑞医药",
                "condition": "继续看突破后承接是否稳住，若量能衰减且回落失守关键均线，则转回观察。",
                "module_source": "position_and_trade_judgement",
            },
            {
                "name": "万邦医药",
                "condition": "即使继续走强，也只保留观察，不自动升级为买入候选。",
                "module_source": "position_and_trade_judgement",
            },
            {
                "name": "其他观察股",
                "condition": "只看趋势改善或恶化，不触发自动买入。",
                "module_source": "position_and_trade_judgement",
            },
        ],
    }


def build_report() -> dict[str, Any]:
    handoff = load_json(HANDOFF_PATH)
    retest = load_json(RETEST_PATH)
    state = load_json(STATE_PATH)
    state_hash = file_sha256(STATE_PATH)
    return {
        "report_name": "股票AI交易助手日报",
        "report_date": "20260706",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "official_state_hash": state_hash,
        "official_state_hash_expected": FORMAL_HASH,
        "official_state_hash_preserved": state_hash == FORMAL_HASH,
        "boundary_flags": {
            "candidate_pool_manual_modified": False,
            "simulated_account_state_modified": False,
            "real_order_placed": False,
            "real_account_connected": False,
            "auto_trading_enabled": False,
            "full_pipeline_enabled": False,
            "news_module_enabled": False,
        },
        "global_disclaimer": {
            "summary": "本日报为统一观察与判断输出，不代表自动交易。BUY_CANDIDATE 仅表示小仓试错候选，WATCH / WATCH_ONLY 仅表示观察。",
            "module_source": "unified",
        },
        "market_and_selection": make_market_summary(handoff),
        "position_and_trade_judgement": make_position_and_trade_summary(retest, state),
    }


def render_md(report: dict[str, Any]) -> str:
    market = report["market_and_selection"]
    trade = report["position_and_trade_judgement"]

    def stock_line(item: dict[str, Any]) -> str:
        return f"- {item['name']} {item['ts_code']}：{item.get('note') or item.get('summary') or item.get('advice')}"

    lines = [
        "# 股票AI交易助手日报",
        "",
        f"- 日期：{report['report_date']}",
        f"- 生成时间：{report['generated_at']}",
        f"- 正式账户状态未改动：{report['official_state_hash_preserved']}",
        "",
        report["global_disclaimer"]["summary"],
        "",
        "## 一、市场与选股部分",
        f"- 市场天气：{market['market_weather']['value']}；{market['market_weather']['summary']}",
        "- 当前阶段主线：化学制药。",
        "- 潜在主线：养殖业，仍需继续验证持续性。",
        "- 情绪热点：医药修复方向仍是当前最清晰的观察中心。",
        "- 中长期资金方向：继续围绕医药主线容量核心和趋势持续性观察。",
        "- 退潮预警：RISK_OFF / OBSERVE_ONLY，下阶段不适合全面进攻，尤其不宜追高扩仓。",
        "- 短线候选股：",
    ]
    lines.extend(stock_line(item) for item in market["short_term_candidate_stocks"])
    lines += ["- 中长线观察股："]
    lines.extend(stock_line(item) for item in market["mid_long_term_watch_stocks"])
    lines += ["- 只观察股票："]
    lines.extend(stock_line(item) for item in market["watch_only_stocks"])
    lines += ["- 明日重点板块观察条件："]
    lines.extend(f"- {item['name']}：{item['condition']}" for item in market["tomorrow_sector_watch_conditions"])
    lines += [
        "",
        "## 二、持仓与交易判断部分",
        f"- 当前模拟持仓：{trade['current_simulated_positions']['summary']}",
    ]
    buy_item = trade["candidate_buy_point_status"]["items"][0]
    lines.append(
        f"- 当前候选股是否触发模拟买点：恒瑞医药 600276.SH，quote_data_source={buy_item['quote_data_source']}，"
        f"quote_trade_date={buy_item['quote_trade_date']}，latest_quote_loaded={buy_item['latest_quote_loaded']}，"
        f"buy_point_data_ready={buy_item['buy_point_data_ready']}，最新价 {buy_item['latest_price']}，"
        f"买点质量 {buy_item['buy_point_quality']}，触发结果 {buy_item['simulated_buy_point_triggered']}，仍需人工确认。"
    )
    lines.append(f"- 买点判断来源：{buy_item['buy_point_judgement_source']}。")
    lines.append(f"- 差异说明：{buy_item['change_explanation']}")
    lines.append("- 风险限制：即使买点触发，当前市场仍是 RISK_OFF / OBSERVE_ONLY，只允许人工确认后的小仓试错，不允许自动买入。")
    lines.append("- WATCH 股票是否升级/降级：本轮仅输出观察结论，不自动升级为买入。")
    lines.append("- 每只股票的操作建议：")
    for item in trade["operation_advice_by_stock"]:
        lines.append(f"- {item['name']} {item['ts_code']}：{item['advice']}")
        lines.append(f"  买点条件：{item['buy_point_condition']}")
        lines.append(f"  止损条件：{item['stop_loss_condition']}")
        lines.append(f"  止盈条件：{item['take_profit_condition']}")
        lines.append(f"  不参与条件：{item['do_not_participate_condition']}")
        lines.append(f"  明日操作观察条件：{item['next_day_watch_condition']}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = build_report()
    OUTPUT_JSON_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    OUTPUT_MD_PATH.write_text(render_md(report), encoding="utf-8")
    print(json.dumps({"json": str(OUTPUT_JSON_PATH), "md": str(OUTPUT_MD_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
