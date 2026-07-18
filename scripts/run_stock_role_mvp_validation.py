from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.execution_decision_engine import decide_execution_from_dict
from scoring_system.stock_role_classifier import classify_stock_role_from_dict


REPORT_DIR = ROOT / "reports" / "stock_role"
REPORT_PATH = REPORT_DIR / "stock_role_mvp_validation_20260704.md"
JSON_PATH = REPORT_DIR / "stock_role_mvp_validation_20260704.json"
SCORES_DIR = ROOT / "data" / "processed" / "scores"
SQLITE_PATH = ROOT / "data" / "sqlite" / "market_120d.sqlite"


def synthetic_cases() -> list[dict[str, Any]]:
    return [
        {"group": "样本1：半导体高位", "name": "有研新材", "ts_code": "600206.SH", "stock_score": 78, "leader_score": 86, "trend_structure_score": 24, "volume_price_quality_score": 20, "position_heat_score": 8, "tradability_score": 14, "pct_chg": 8.5, "leader_labels": "容量核心", "risk_text": "位置过热", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH", "expected": "高位核心不追，保护利润。"},
        {"group": "样本1：半导体高位", "name": "雅克科技", "ts_code": "002409.SZ", "stock_score": 82, "leader_score": 90, "trend_structure_score": 29, "volume_price_quality_score": 22, "position_heat_score": 9, "tradability_score": 15, "pct_chg": 4.2, "leader_labels": "趋势核心、容量核心", "risk_text": "位置过热", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH", "expected": "趋势/容量核心，但高潮阶段不追。"},
        {"group": "样本1：半导体高位", "name": "长光华芯", "ts_code": "688048.SH", "stock_score": 70, "leader_score": 68, "trend_structure_score": 20, "volume_price_quality_score": 16, "position_heat_score": 6, "tradability_score": 9, "pct_chg": 12.0, "leader_labels": "观察", "risk_text": "位置过热；最近5日波动过大", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH", "expected": "补涨或后排，高位压制。"},
        {"group": "样本1：半导体高位", "name": "神工股份", "ts_code": "688233.SH", "stock_score": 60, "leader_score": 55, "trend_structure_score": 16, "volume_price_quality_score": 12, "position_heat_score": 7, "tradability_score": 8, "pct_chg": 6.5, "leader_labels": "观察", "risk_text": "放量但收盘位置弱", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH", "expected": "后排或角色不足，不追。"},
        {"group": "样本1：半导体高位", "name": "颀中科技", "ts_code": "688352.SH", "stock_score": 58, "leader_score": 50, "trend_structure_score": 14, "volume_price_quality_score": 11, "position_heat_score": 5, "tradability_score": 8, "pct_chg": -3.0, "leader_labels": "观察", "risk_text": "跌破MA20", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH", "expected": "弱结构规避。"},
        {"group": "样本1：半导体高位", "name": "新相微", "ts_code": "688593.SH", "stock_score": 66, "leader_score": 62, "trend_structure_score": 18, "volume_price_quality_score": 15, "position_heat_score": 8, "tradability_score": 7, "pct_chg": 9.0, "leader_labels": "观察", "risk_text": "位置过热", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH", "expected": "补涨不当龙头。"},
        {"group": "样本1：半导体高位", "name": "盛合晶微", "ts_code": "688000.SH", "stock_score": 62, "leader_score": 58, "trend_structure_score": 17, "volume_price_quality_score": 14, "position_heat_score": 6, "tradability_score": 7, "pct_chg": 5.0, "leader_labels": "观察", "risk_text": "", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH", "expected": "后排跟随，不作为主买点。"},
        {"group": "样本2：电子化学品分歧", "name": "鼎龙股份", "ts_code": "300054.SZ", "stock_score": 80, "leader_score": 88, "trend_structure_score": 28, "volume_price_quality_score": 21, "position_heat_score": 8, "tradability_score": 14, "pct_chg": -2.5, "leader_labels": "趋势核心、容量核心", "risk_text": "位置过热", "sector_cycle": "DIVERGENCE", "sector_aux_labels": ["HIGH_LEVEL_UNSTABLE", "WAIT_FOR_CONFIRMATION"], "sector_confidence": "MEDIUM", "expected": "核心只观察承接，不直接买。"},
        {"group": "样本2：电子化学品分歧", "name": "晶瑞电材", "ts_code": "300655.SZ", "stock_score": 68, "leader_score": 66, "trend_structure_score": 18, "volume_price_quality_score": 13, "position_heat_score": 6, "tradability_score": 8, "pct_chg": -5.0, "leader_labels": "观察", "risk_text": "放量但收盘位置弱", "sector_cycle": "DIVERGENCE", "sector_aux_labels": ["HIGH_LEVEL_UNSTABLE"], "sector_confidence": "MEDIUM", "expected": "后排/补涨风险降低。"},
        {"group": "样本2：电子化学品分歧", "name": "中巨芯", "ts_code": "688549.SH", "stock_score": 61, "leader_score": 55, "trend_structure_score": 13, "volume_price_quality_score": 10, "position_heat_score": 5, "tradability_score": 7, "pct_chg": -6.0, "leader_labels": "观察", "risk_text": "跌破MA20", "sector_cycle": "DIVERGENCE", "sector_aux_labels": ["BACKROW_RISK_SPREAD"], "sector_confidence": "MEDIUM", "expected": "弱结构规避。"},
        {"group": "样本2：电子化学品分歧", "name": "思泉新材", "ts_code": "301489.SZ", "stock_score": 64, "leader_score": 60, "trend_structure_score": 16, "volume_price_quality_score": 12, "position_heat_score": 6, "tradability_score": 7, "pct_chg": 7.5, "leader_labels": "观察", "risk_text": "位置过热", "sector_cycle": "DIVERGENCE", "sector_aux_labels": ["BACKROW_RISK_SPREAD"], "sector_confidence": "MEDIUM", "expected": "分歧中补涨不追。"},
        {"group": "样本2：电子化学品分歧", "name": "天通股份", "ts_code": "600330.SH", "stock_score": 57, "leader_score": 52, "trend_structure_score": 15, "volume_price_quality_score": 11, "position_heat_score": 7, "tradability_score": 9, "pct_chg": -1.5, "leader_labels": "观察", "risk_text": "", "sector_cycle": "DIVERGENCE", "sector_aux_labels": ["WAIT_FOR_CONFIRMATION"], "sector_confidence": "MEDIUM", "expected": "后排等待，不直接买。"},
        {"group": "样本3：航天装备结构性机会", "name": "中国卫星", "ts_code": "600118.SH", "stock_score": 76, "leader_score": 86, "trend_structure_score": 27, "volume_price_quality_score": 18, "position_heat_score": 12, "tradability_score": 15, "pct_chg": 2.5, "leader_labels": "容量核心、趋势核心", "risk_text": "", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM", "expected": "容量/趋势核心，可观察小仓。"},
        {"group": "样本3：航天装备结构性机会", "name": "航天电子", "ts_code": "600879.SH", "stock_score": 78, "leader_score": 88, "trend_structure_score": 26, "volume_price_quality_score": 19, "position_heat_score": 12, "tradability_score": 14, "pct_chg": 3.0, "leader_labels": "趋势核心", "risk_text": "", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM", "expected": "核心观察，不放大成全面强势。"},
        {"group": "样本3：航天装备结构性机会", "name": "电科蓝天", "ts_code": "000000.SZ", "stock_score": 62, "leader_score": 58, "trend_structure_score": 17, "volume_price_quality_score": 12, "position_heat_score": 9, "tradability_score": 7, "pct_chg": 6.2, "leader_labels": "观察", "risk_text": "", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM", "expected": "后排或补涨，不放大。"},
        {"group": "样本3：航天装备结构性机会", "name": "中天火箭", "ts_code": "003009.SZ", "stock_score": 66, "leader_score": 63, "trend_structure_score": 18, "volume_price_quality_score": 13, "position_heat_score": 8, "tradability_score": 8, "pct_chg": 8.0, "leader_labels": "观察", "risk_text": "位置过热", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM", "expected": "补涨候选小心，不当核心。"},
        {"group": "样本3：航天装备结构性机会", "name": "新余国科", "ts_code": "300722.SZ", "stock_score": 60, "leader_score": 55, "trend_structure_score": 15, "volume_price_quality_score": 12, "position_heat_score": 8, "tradability_score": 7, "pct_chg": 4.5, "leader_labels": "观察", "risk_text": "", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM", "expected": "后排观察。"},
        {"group": "样本3：航天装备结构性机会", "name": "星网宇达", "ts_code": "002829.SZ", "stock_score": 54, "leader_score": 50, "trend_structure_score": 12, "volume_price_quality_score": 10, "position_heat_score": 6, "tradability_score": 6, "pct_chg": -2.0, "leader_labels": "观察", "risk_text": "跌破MA20", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM", "expected": "弱结构规避。"},
        {"group": "样本3：航天装备结构性机会", "name": "理工导航", "ts_code": "688282.SH", "stock_score": 59, "leader_score": 53, "trend_structure_score": 15, "volume_price_quality_score": 11, "position_heat_score": 7, "tradability_score": 6, "pct_chg": 1.0, "leader_labels": "观察", "risk_text": "", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM", "expected": "后排或角色不确定。"},
    ]


def latest_date() -> str | None:
    dates: list[str] = []
    for path in SCORES_DIR.glob("stock_scores_*.csv"):
        dates.extend([p for p in path.stem.split("_") if p.isdigit() and len(p) == 8])
    return max(dates) if dates else None


def latest_quotes(as_of: str) -> pd.DataFrame:
    if not SQLITE_PATH.exists():
        return pd.DataFrame()
    with sqlite3.connect(SQLITE_PATH) as conn:
        return pd.read_sql_query(
            "SELECT ts_code, close, pct_chg, amount_yuan, turnover_rate FROM daily LEFT JOIN daily_basic USING(ts_code, trade_date) WHERE trade_date = ?",
            conn,
            params=(as_of,),
        )


def daily_candidate_cases(limit: int = 8) -> list[dict[str, Any]]:
    as_of = latest_date()
    if not as_of:
        return []
    path = SCORES_DIR / f"stock_scores_{as_of}.csv"
    if not path.exists():
        return []
    stocks = pd.read_csv(path, dtype={"ts_code": "string"}).sort_values(["stock_score", "leader_score"], ascending=False).head(limit)
    quote_map = latest_quotes(as_of).set_index("ts_code").to_dict("index") if not latest_quotes(as_of).empty else {}
    rows: list[dict[str, Any]] = []
    for _, row in stocks.iterrows():
        q = quote_map.get(str(row.get("ts_code")), {})
        rows.append({
            "group": "样本4：最新日常候选",
            "name": row.get("name"),
            "ts_code": row.get("ts_code"),
            "stock_score": row.get("stock_score"),
            "leader_score": row.get("leader_score"),
            "trend_structure_score": row.get("trend_structure_score"),
            "volume_price_quality_score": row.get("volume_price_quality_score"),
            "position_heat_score": row.get("position_heat_score"),
            "tradability_score": row.get("tradability_score"),
            "pct_chg": q.get("pct_chg"),
            "turnover_rate": q.get("turnover_rate"),
            "leader_labels": row.get("leader_labels"),
            "risk_text": row.get("basic_risk"),
            "execution_status": row.get("execution_status"),
            "sub_scores_json": row.get("sub_scores_json"),
            "sector_cycle": "STARTING",
            "sector_aux_labels": ["STRUCTURAL_START"],
            "sector_confidence": "LOW",
            "expected": "最新候选必须输出新角色，并解释角色是否支持买入。",
        })
    return rows


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    role = classify_stock_role_from_dict(case)
    result = decide_execution_from_dict({
        "ts_code": case.get("ts_code"),
        "name": case.get("name"),
        "stock_score": case.get("stock_score"),
        "leader_score": case.get("leader_score"),
        "original_status": case.get("execution_status", "WAIT_CONFIRM"),
        "sector_name": case.get("group", ""),
        "sector_cycle": case.get("sector_cycle", "UNKNOWN"),
        "sector_aux_labels": case.get("sector_aux_labels", []),
        "sector_confidence": case.get("sector_confidence", "LOW"),
        "risk_text": case.get("risk_text", ""),
        "leader_labels": case.get("leader_labels", ""),
        "core_identity": "",
        "stock_role": role["role"],
        "user_state": "empty",
        "can_watch": True,
        "has_alert": True,
    })
    return {
        "group": case["group"],
        "name": case["name"],
        "ts_code": case["ts_code"],
        "expected": case["expected"],
        "role": role,
        "execution_label": result.final_label,
        "allow_buy": result.allow_buy,
        "max_position_pct": result.max_position_pct,
        "reasons": result.downgrade_reasons,
    }


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [run_case(x) for x in synthetic_cases() + daily_candidate_cases()]
    JSON_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 龙头 / 补涨 / 后排识别优化 MVP 小样本验证",
        "",
        "- 本验证只测试角色识别与执行层传导，不修改评分权重。",
        "- 本验证不重跑原七题，不做自动交易。",
        "",
    ]
    current_group = ""
    for row in rows:
        if row["group"] != current_group:
            current_group = row["group"]
            lines.extend([f"## {current_group}", ""])
        role = row["role"]
        lines.extend([
            f"### {row['name']} {row['ts_code']}",
            f"- 预期验证点：{row['expected']}",
            f"- 新角色：{role['role']}（{role['role_name']}），置信度 {role['confidence']}",
            f"- 角色依据：{'；'.join(role['evidence']) or '-'}",
            f"- 角色风险：{'；'.join(role['risks']) or '-'}",
            f"- 是否核心：{'是' if role['is_core'] else '否'}；是否后排：{'是' if role['is_backrow'] else '否'}；是否补涨：{'是' if role['is_catch_up'] else '否'}；是否弱结构：{'是' if role['is_weak_structure'] else '否'}",
            f"- 对执行影响：{role['execution_effect']}",
            f"- 最终执行标签：{row['execution_label']}；允许买：{'是' if row['allow_buy'] else '否'}；最大仓位：{row['max_position_pct']}%",
            f"- 降级/限制原因：{'；'.join(row['reasons'][:3]) or '-'}",
            "",
        ])
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"markdown": str(REPORT_PATH), "json": str(JSON_PATH), "cases": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
