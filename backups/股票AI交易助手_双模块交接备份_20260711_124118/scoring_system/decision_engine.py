from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "processed" / "scores"
DECISIONS = ROOT / "data" / "processed" / "decisions"
REPORTS = ROOT / "reports" / "decision"
MODEL_VERSION = "1.0.0-decision-mvp"
DEFAULT_TEST_STOCKS = ["002409.SZ", "600206.SH", "300346.SZ", "300655.SZ", "688371.SH", "600330.SH", "688696.SH"]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_inputs(as_of: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    stock_path = SCORES / f"stock_scores_{as_of}.csv"
    leader_path = SCORES / f"leader_scores_{as_of}.csv"
    if not stock_path.exists():
        raise FileNotFoundError(f"Missing stock score file: {stock_path}")
    if not leader_path.exists():
        raise FileNotFoundError(f"Missing leader score file: {leader_path}")
    stock = pd.read_csv(stock_path, dtype={"ts_code": "string", "sector_code": "string"})
    leader = pd.read_csv(leader_path, dtype={"ts_code": "string", "sector_code": "string"})
    return stock, leader


def split_text(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    text = str(value)
    for prefix in ["基础行情风险：", "事件风险："]:
        text = text.replace(prefix, "")
    parts = []
    for item in text.replace(",", "；").split("；"):
        item = item.strip()
        if item and item not in {"未触发", "未检查或数据缺失"}:
            parts.append(item)
    return parts


def core_identity(stock_row: pd.Series, leader_row: pd.DataFrame, cfg: dict[str, Any]) -> str:
    labels = str(stock_row.get("leader_labels", ""))
    core_labels = cfg["core_labels"]
    hit_count = sum(1 for label in core_labels if label in labels)
    if hit_count >= int(cfg["identity"]["multi_core_min_labels"]):
        return "MULTI_CORE"
    if hit_count == 1:
        return "CORE"
    if len(leader_row):
        grade = str(leader_row.iloc[0].get("grade", ""))
        if any(grade.startswith(prefix) for prefix in cfg["identity"]["secondary_grade_prefixes"]):
            return "SECONDARY"
    leader_score = pd.to_numeric(pd.Series([stock_row.get("leader_score")]), errors="coerce").iloc[0]
    if not pd.isna(leader_score) and leader_score >= float(cfg["identity"]["follower_min_leader_score"]):
        return "FOLLOWER"
    return "WEAK"


def mapped_conclusion(stock_status: str, identity: str, cfg: dict[str, Any]) -> str:
    mapping = cfg["stock_status_mapping"].get(stock_status, {})
    if identity in mapping:
        return mapping[identity]
    return mapping.get("default", "WAIT_CONFIRM")


def apply_gates(conclusion: str, row: pd.Series, cfg: dict[str, Any], notes: list[str]) -> str:
    if conclusion in {"AVOID", "WEAK_STRUCTURE", "DATA_INSUFFICIENT"}:
        return conclusion
    market_score = pd.to_numeric(pd.Series([row.get("market_score")]), errors="coerce").iloc[0]
    if conclusion == "READY_CORE" and not pd.isna(market_score) and market_score < float(cfg["market_gate"]["ready_core_min_market_score"]):
        notes.append("市场低于门控阈值，READY_CORE降级为WAIT_CONFIRM")
        conclusion = cfg["market_gate"]["downgrade_to"]
    if conclusion in {"READY_CORE", "READY_SECONDARY"}:
        sector_grade = str(row.get("sector_grade", ""))
        if not any(sector_grade.startswith(prefix) for prefix in cfg["sector_gate"]["min_grade_prefix_for_ready"]):
            notes.append("板块低于C级，READY降级为WAIT_CONFIRM")
            conclusion = cfg["sector_gate"]["downgrade_to"]
    return conclusion


def decision_for_row(row: pd.Series, leader: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, Any]:
    leader_row = leader[leader["ts_code"].astype(str) == str(row["ts_code"])].head(1)
    identity = core_identity(row, leader_row, cfg)
    notes: list[str] = []
    conclusion = mapped_conclusion(str(row["execution_status"]), identity, cfg)
    conclusion = apply_gates(conclusion, row, cfg, notes)
    if conclusion == "READY_SECONDARY" and identity not in {"CORE", "MULTI_CORE"}:
        notes.append(cfg["notes"]["non_core_ready"])

    advantages = split_text(row.get("advantages"))[: int(cfg["output"]["max_advantages"])]
    risks = split_text(row.get("basic_risk"))[: int(cfg["output"]["max_risks"])]
    waits = split_text(row.get("wait_or_stop_conditions"))
    invalidations = [x for x in waits if "不做" in x or "重新站回" in x or "终止" in x]
    waits_only = [x for x in waits if x not in invalidations]
    if notes:
        waits_only.extend(notes)

    return {
        "trade_date": str(row["trade_date"]),
        "ts_code": str(row["ts_code"]),
        "name": str(row["name"]),
        "market_score": none_if_nan(row.get("market_score")),
        "market_grade": str(row.get("market_grade", "")),
        "sector_code": str(row.get("sector_code", "")),
        "sector_name": str(row.get("sector_name", "")),
        "sector_score": none_if_nan(row.get("sector_score")),
        "sector_grade": str(row.get("sector_grade", "")),
        "leader_score": none_if_nan(row.get("leader_score")),
        "leader_labels": str(row.get("leader_labels", "非核心候选")),
        "core_identity": identity,
        "stock_score": none_if_nan(row.get("stock_score")),
        "stock_execution_status": str(row.get("execution_status", "")),
        "final_decision": conclusion,
        "current_stage": cfg["stage_text"].get(conclusion, conclusion),
        "advantages": advantages[: int(cfg["output"]["max_advantages"])],
        "risks": risks[: int(cfg["output"]["max_risks"])],
        "wait_conditions": waits_only[:3],
        "invalid_conditions": invalidations[:3],
        "event_risk": cfg["notes"]["event_risk"],
        "data_quality": none_if_nan(row.get("data_quality")),
        "detail_scores": {
            "trend_structure_score": none_if_nan(row.get("trend_structure_score")),
            "volume_price_quality_score": none_if_nan(row.get("volume_price_quality_score")),
            "position_heat_score": none_if_nan(row.get("position_heat_score")),
            "tradability_score": none_if_nan(row.get("tradability_score")),
            "stock_sub_scores": parse_json(row.get("sub_scores_json")),
        },
    }


def none_if_nan(value: Any) -> Any:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def parse_json(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return None


def write_outputs(as_of: str, decisions: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, str]:
    DECISIONS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    json_path = DECISIONS / f"decision_results_{as_of}.json"
    csv_path = DECISIONS / f"decision_results_{as_of}.csv"
    md_path = REPORTS / f"decision_report_{as_of}.md"

    payload = {
        "as_of_date": as_of,
        "model_version": MODEL_VERSION,
        "config_version": cfg.get("version"),
        "decisions": decisions,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    flat_rows = []
    for d in decisions:
        flat_rows.append({
            "trade_date": d["trade_date"],
            "ts_code": d["ts_code"],
            "name": d["name"],
            "market_score": d["market_score"],
            "market_grade": d["market_grade"],
            "sector_name": d["sector_name"],
            "sector_score": d["sector_score"],
            "sector_grade": d["sector_grade"],
            "leader_score": d["leader_score"],
            "leader_labels": d["leader_labels"],
            "core_identity": d["core_identity"],
            "stock_score": d["stock_score"],
            "stock_execution_status": d["stock_execution_status"],
            "final_decision": d["final_decision"],
            "current_stage": d["current_stage"],
            "advantages": "；".join(d["advantages"]),
            "risks": "；".join(d["risks"]),
            "wait_conditions": "；".join(d["wait_conditions"]),
            "invalid_conditions": "；".join(d["invalid_conditions"]),
            "event_risk": d["event_risk"],
            "data_quality": d["data_quality"],
        })
    pd.DataFrame(flat_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")

    lines = [
        f"# 一键决策报告 {as_of}",
        "",
        f"模型版本：{MODEL_VERSION}",
        "说明：本报告只组合四层已有结果，不重新加权评分，不给仓位建议。",
        "",
        "| 股票 | 代码 | 市场 | 板块 | 龙头身份 | 个股状态 | 最终结论 | 当前阶段 | 主要优势 | 主要风险 | 等待条件 | 失效条件 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for d in decisions:
        lines.append(
            f"| {d['name']} | {d['ts_code']} | {fmt_score(d['market_score'])} / {d['market_grade']} | {d['sector_name']} {fmt_score(d['sector_score'])} / {d['sector_grade']} | {fmt_score(d['leader_score'])} / {d['core_identity']} | {fmt_score(d['stock_score'])} / {d['stock_execution_status']} | {d['final_decision']} | {d['current_stage']} | {join_or_dash(d['advantages'])} | {join_or_dash(d['risks'])} | {join_or_dash(d['wait_conditions'])} | {join_or_dash(d['invalid_conditions'])} |"
        )
    lines.extend([
        "",
        "事件风险：未检查或数据缺失。",
    ])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "markdown": str(md_path)}


def fmt_score(value: Any) -> str:
    if value is None or pd.isna(value):
        return "无"
    return f"{float(value):.2f}"


def join_or_dash(items: list[str]) -> str:
    return "；".join(items) if items else "-"


def run_decision(as_of: str = "20260630", stock: str | None = None, no_api: bool = True) -> dict[str, Any]:
    cfg = load_yaml(ROOT / "config" / "decision_rules.yaml")
    stock_df, leader_df = load_inputs(as_of)
    if stock:
        targets = [stock]
        selected = stock_df[stock_df["ts_code"].astype(str).isin(targets)].copy()
        missing = [code for code in targets if code not in set(selected["ts_code"].astype(str))]
        if missing:
            raise RuntimeError(f"Missing stock score rows for: {', '.join(missing)}. Run stock score first.")
        selected["_order"] = selected["ts_code"].astype(str).map({code: i for i, code in enumerate(targets)})
        selected = selected.sort_values("_order")
    else:
        available_codes = stock_df["ts_code"].astype(str).tolist()
        if not available_codes:
            raise RuntimeError("Stock score file is empty. Run stock score first.")
        preferred = [code for code in DEFAULT_TEST_STOCKS if code in available_codes]
        remainder = [code for code in available_codes if code not in preferred]
        targets = preferred + remainder
        selected = stock_df.copy()
        selected["_order"] = selected["ts_code"].astype(str).map({code: i for i, code in enumerate(targets)})
        selected = selected.sort_values("_order")
    decisions = [decision_for_row(row, leader_df, cfg) for _, row in selected.iterrows()]
    paths = write_outputs(as_of, decisions, cfg)
    result = {
        "as_of_date": as_of,
        "stock_count": len(decisions),
        "decision_counts": pd.Series([d["final_decision"] for d in decisions]).value_counts().to_dict(),
        "paths": paths,
        "no_api": no_api,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", default=None)
    parser.add_argument("--as-of", default="")
    parser.add_argument("--no-api", action="store_true", help="显式离线运行；本脚本不调用外部接口")
    args = parser.parse_args()
    if not args.as_of:
        from scoring_system.report_freshness import freshness_snapshot

        snap = freshness_snapshot()
        args.as_of = snap.get("stock_score_date", "") or snap.get("leader_score_date", "")
    run_decision(as_of=args.as_of, stock=args.stock, no_api=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
