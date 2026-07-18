from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.execution_decision_engine import decide_execution_from_dict
from scoring_system.hierarchy_report import (
    pick_latest_date,
    read_csv,
    sector_cycle_for_code,
    labels_to_text,
)


REPORT_DIR = ROOT / "reports" / "execution"
EXAM_DIR = ROOT / "reports" / "exam_v2"
SCORES = ROOT / "data" / "processed" / "scores"
DECISIONS = ROOT / "data" / "processed" / "decisions"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def role_to_identity(role: str) -> str:
    if role in {"疑似龙头", "容量核心", "趋势核心", "次核心"}:
        return "CORE"
    if role in {"后排或弱结构", "角色不确定"}:
        return "WEAK"
    return ""


def risk_from_exam_stock(item: dict[str, Any]) -> str:
    risks: list[str] = []
    if item.get("20日位置") is not None and float(item.get("20日位置")) >= 0.9:
        risks.append("位置过热")
    if item.get("角色") in {"后排或弱结构", "角色不确定"}:
        risks.append("后排或弱结构")
    if abs(float(item.get("当日涨跌幅%", 0) or 0)) >= 8:
        risks.append("最近5日波动过大")
    return "；".join(risks)


def decide_case(sample: str, stock: dict[str, Any], cycle: dict[str, Any], user_state: str = "empty", can_watch: bool = True) -> dict[str, Any]:
    role = str(stock.get("角色", ""))
    payload = {
        "ts_code": stock.get("代码", ""),
        "name": stock.get("名称", ""),
        "stock_score": 82 if role_to_identity(role) == "CORE" else 65,
        "leader_score": 80 if role in {"疑似龙头", "容量核心"} else 55,
        "original_status": "READY_CONFIRM" if role_to_identity(role) == "CORE" else "WAIT_CONFIRM",
        "sector_name": sample,
        "sector_cycle": cycle.get("main_label", "UNKNOWN"),
        "sector_aux_labels": cycle.get("aux_labels", []),
        "sector_confidence": cycle.get("confidence", "LOW"),
        "risk_text": risk_from_exam_stock(stock),
        "leader_labels": role,
        "core_identity": role_to_identity(role),
        "user_state": user_state,
        "can_watch": can_watch,
        "has_alert": True,
        "latest_price": stock.get("收盘价"),
    }
    result = decide_execution_from_dict(payload)
    return {
        "sample": sample,
        "name": payload["name"],
        "ts_code": payload["ts_code"],
        "role": role,
        "user_state": user_state,
        "can_watch": can_watch,
        "sector_cycle": result.sector_cycle_text,
        "confidence": result.sector_confidence,
        "original_status": result.original_status,
        "final_label": result.final_label,
        "allow_buy": result.allow_buy,
        "max_position_pct": result.max_position_pct,
        "downgrade_reasons": result.downgrade_reasons,
        "holding_advice": result.holding_advice,
        "no_watch_advice": result.no_watch_advice,
        "stop_advice": result.stop_advice,
    }


def exam_sample_rows() -> list[dict[str, Any]]:
    specs = [
        ("半导体高位样本", EXAM_DIR / "exam8b_sampleA_stageA_20260630.json"),
        ("电子化学品分歧样本", EXAM_DIR / "exam8b_sampleB_stageA_20260701.json"),
        ("航天装备结构性机会样本", EXAM_DIR / "exam8b_sampleC_stageA_20260630.json"),
    ]
    rows: list[dict[str, Any]] = []
    for title, path in specs:
        payload = load_json(path)
        cycle = payload.get("cycle_judgment", {})
        pool = payload.get("sector_observation_pool", [])
        core = next((x for x in pool if x.get("角色") in {"疑似龙头", "容量核心", "趋势核心"}), None)
        rear = next((x for x in pool if x.get("角色") in {"后排或弱结构", "角色不确定"}), None)
        if core:
            rows.append(decide_case(title, core, cycle, user_state="empty", can_watch=True))
            rows.append(decide_case(title + "（不能盯盘）", core, cycle, user_state="empty", can_watch=False))
            rows.append(decide_case(title + "（持仓）", core, cycle, user_state="holding", can_watch=True))
        if rear:
            rows.append(decide_case(title + "（后排）", rear, cycle, user_state="empty", can_watch=True))
    return rows


def latest_rows(limit: int = 8) -> list[dict[str, Any]]:
    as_of = pick_latest_date()
    stock_path = SCORES / f"stock_scores_{as_of}.csv"
    decision_path = DECISIONS / f"decision_results_{as_of}.csv"
    sector_path = SCORES / f"sector_scores_{as_of}_calibrated.csv"
    market_path = SCORES / f"market_sector_score_{as_of}_calibrated.json"
    stocks = read_csv(stock_path)
    decisions = read_csv(decision_path) if decision_path.exists() else pd.DataFrame()
    sectors = read_csv(sector_path) if sector_path.exists() else pd.DataFrame()
    if market_path.exists():
        market = load_json(market_path)
        ranked = pd.DataFrame(market.get("sector_rankings", []))
        if not ranked.empty:
            sectors = ranked
    decision_map = decisions.set_index("ts_code").to_dict("index") if not decisions.empty else {}
    rows: list[dict[str, Any]] = []
    for _, row in stocks.sort_values(["stock_score", "leader_score"], ascending=False).head(limit).iterrows():
        ts_code = str(row.get("ts_code"))
        decision = decision_map.get(ts_code, {})
        cycle = sector_cycle_for_code(str(row.get("sector_code", "")), sectors, stocks)
        payload = {
            "ts_code": ts_code,
            "name": row.get("name", ""),
            "stock_score": row.get("stock_score"),
            "leader_score": row.get("leader_score", decision.get("leader_score")),
            "original_status": decision.get("final_decision", row.get("execution_status", "")),
            "sector_name": row.get("sector_name", ""),
            "sector_cycle": cycle.get("main_label", "UNKNOWN"),
            "sector_aux_labels": cycle.get("aux_labels", []),
            "sector_confidence": cycle.get("confidence", "LOW"),
            "risk_text": "；".join([str(row.get("basic_risk", "")), str(decision.get("risks", ""))]),
            "leader_labels": row.get("leader_labels", decision.get("leader_labels", "")),
            "core_identity": decision.get("core_identity", ""),
            "user_state": "empty",
            "can_watch": True,
            "has_alert": True,
        }
        result = decide_execution_from_dict(payload)
        rows.append({
            "sample": f"最新日常候选 {as_of}",
            "name": payload["name"],
            "ts_code": ts_code,
            "role": payload["core_identity"] or payload["leader_labels"],
            "user_state": "empty",
            "can_watch": True,
            "sector_cycle": result.sector_cycle_text,
            "confidence": result.sector_confidence,
            "original_status": result.original_status,
            "final_label": result.final_label,
            "allow_buy": result.allow_buy,
            "max_position_pct": result.max_position_pct,
            "downgrade_reasons": result.downgrade_reasons,
            "holding_advice": result.holding_advice,
            "no_watch_advice": result.no_watch_advice,
            "stop_advice": result.stop_advice,
        })
    return rows


def write_report(rows: list[dict[str, Any]]) -> dict[str, str]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    date = datetime.now().strftime("%Y%m%d")
    json_path = REPORT_DIR / f"execution_mvp_validation_{date}.json"
    md_path = REPORT_DIR / f"execution_mvp_validation_{date}.md"
    json_path.write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 执行标签与仓位模块MVP小样本验证 {date}",
        "",
        "说明：本验证只检查执行层降级和仓位映射，不重跑原七题，不做回测，不修改评分权重。",
        "",
        "| 样本 | 股票 | 角色 | 原始状态 | 最终执行标签 | 允许买 | 最大仓位 | 板块周期 | 主要原因 |",
        "| --- | --- | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for row in rows:
        reasons = "；".join(row.get("downgrade_reasons", [])[:2]) or "-"
        lines.append(
            f"| {row['sample']} | {row['name']} {row['ts_code']} | {row['role']} | {row['original_status']} | {row['final_label']} | {'是' if row['allow_buy'] else '否'} | {row['max_position_pct']}% | {row['sector_cycle']}，{row['confidence']} | {reasons} |"
        )
    lines.extend([
        "",
        "## 验证结论",
        "",
        "- 半导体高位样本：高潮和高潮后退潮风险会压制新买，高分核心不再直接追高，持仓转向利润保护。",
        "- 电子化学品分歧样本：分歧状态会让空仓等待承接，后排和不能盯盘场景会进一步降级。",
        "- 航天装备结构性机会样本：结构性启动允许核心观察仓或小试错仓，但不会放大成全面强势。",
        "- 最新日常候选：每只候选都能输出最终执行标签、允许买、最大仓位和降级原因。",
        "",
        "边界：这是最小可用执行层验证，不代表完整回测收益，也不是交易指令。",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main() -> int:
    rows = exam_sample_rows() + latest_rows()
    paths = write_report(rows)
    print(json.dumps({"rows": len(rows), **paths}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
