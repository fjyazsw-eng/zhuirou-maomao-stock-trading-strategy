from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.account_position_manager import (
    candidate_from_dict,
    decide_account_position,
    decision_to_dict,
    holding_from_dict,
)


REPORT_DIR = ROOT / "reports" / "account"
REPORT_MD = REPORT_DIR / "account_position_mvp_validation_20260704.md"
REPORT_JSON = REPORT_DIR / "account_position_mvp_validation_20260704.json"


def case_payloads() -> list[dict[str, Any]]:
    return [
        {
            "title": "样本1：空仓账户",
            "total_asset": 50000,
            "cash": 50000,
            "market_weather": "风险环境",
            "can_watch": True,
            "holdings": [],
            "candidates": [
                {"ts_code": "A1", "name": "观察股A", "sector_code": "S1", "sector_name": "半导体", "stock_role": "TREND_CORE", "final_execution_label": "OBSERVE_ONLY", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH"},
                {"ts_code": "A2", "name": "观察股B", "sector_code": "S2", "sector_name": "电子化学品", "stock_role": "CATCH_UP", "final_execution_label": "WAIT_FOR_SUPPORT", "sector_cycle": "DIVERGENCE", "sector_aux_labels": [], "sector_confidence": "MEDIUM"},
            ],
            "expected": "保持现金，不因为有候选就买，总仓位上限受风险环境限制。",
        },
        {
            "title": "样本2：轻仓账户",
            "total_asset": 50000,
            "cash": 40000,
            "market_weather": "风险环境",
            "can_watch": True,
            "holdings": [
                {"ts_code": "H1", "name": "已有核心", "shares": 500, "cost": 20, "current_price": 20, "sector_code": "S1", "sector_name": "物流", "stock_role": "TREND_CORE", "final_execution_label": "HOLD_WITH_PROTECTION", "holding_label": "HOLD_NORMAL", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM"},
            ],
            "candidates": [
                {"ts_code": "C1", "name": "试错核心", "sector_code": "S2", "sector_name": "航天装备", "stock_role": "CAPACITY_CORE", "final_execution_label": "READY_TRIAL", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM"},
            ],
            "expected": "允许小仓，但不能超过账户总仓位上限和单票上限。",
        },
        {
            "title": "样本3：重仓账户",
            "total_asset": 50000,
            "cash": 10000,
            "market_weather": "风险环境",
            "can_watch": True,
            "holdings": [
                {"ts_code": "H1", "name": "重仓核心1", "shares": 1000, "cost": 20, "current_price": 20, "sector_code": "S1", "sector_name": "半导体", "stock_role": "LEADER", "final_execution_label": "HOLD_WITH_PROTECTION", "holding_label": "HOLD_WITH_PROTECTION", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH"},
                {"ts_code": "H2", "name": "重仓核心2", "shares": 1000, "cost": 20, "current_price": 20, "sector_code": "S2", "sector_name": "电子", "stock_role": "TREND_CORE", "final_execution_label": "OBSERVE_ONLY", "holding_label": "HOLD_WITH_PROTECTION", "sector_cycle": "DIVERGENCE", "sector_aux_labels": [], "sector_confidence": "MEDIUM"},
            ],
            "candidates": [
                {"ts_code": "C1", "name": "新候选", "sector_code": "S3", "sector_name": "医药", "stock_role": "LEADER", "final_execution_label": "READY_CONFIRM", "sector_cycle": "FERMENTING", "sector_aux_labels": [], "sector_confidence": "HIGH"},
            ],
            "expected": "提示总仓位过高，禁止新买，建议降风险。",
        },
        {
            "title": "样本4：板块集中账户",
            "total_asset": 50000,
            "cash": 20000,
            "market_weather": "普通环境",
            "can_watch": True,
            "holdings": [
                {"ts_code": "H1", "name": "同板块1", "shares": 500, "cost": 20, "current_price": 20, "sector_code": "S1", "sector_name": "半导体", "stock_role": "LEADER", "final_execution_label": "HOLD_WITH_PROTECTION", "holding_label": "HOLD_WITH_PROTECTION", "sector_cycle": "DIVERGENCE", "sector_aux_labels": [], "sector_confidence": "MEDIUM"},
                {"ts_code": "H2", "name": "同板块2", "shares": 500, "cost": 20, "current_price": 20, "sector_code": "S1", "sector_name": "半导体", "stock_role": "FOLLOWER", "final_execution_label": "BREAKDOWN_AVOID", "holding_label": "REDUCE_RISK", "sector_cycle": "DIVERGENCE", "sector_aux_labels": [], "sector_confidence": "MEDIUM"},
                {"ts_code": "H3", "name": "同板块3", "shares": 500, "cost": 20, "current_price": 20, "sector_code": "S1", "sector_name": "半导体", "stock_role": "CATCH_UP", "final_execution_label": "OVERHEATED_NO_CHASE", "holding_label": "REDUCE_PROFIT_PROTECTION", "sector_cycle": "DIVERGENCE", "sector_aux_labels": [], "sector_confidence": "MEDIUM"},
            ],
            "candidates": [
                {"ts_code": "C1", "name": "同板块新股", "sector_code": "S1", "sector_name": "半导体", "stock_role": "TREND_CORE", "final_execution_label": "READY_TRIAL", "sector_cycle": "DIVERGENCE", "sector_aux_labels": [], "sector_confidence": "MEDIUM"},
            ],
            "expected": "识别板块过度集中，不继续加同板块，建议减后排。",
        },
        {
            "title": "样本5：不能盯盘账户",
            "total_asset": 50000,
            "cash": 25000,
            "market_weather": "普通环境",
            "can_watch": False,
            "holdings": [
                {"ts_code": "H1", "name": "高波动持仓", "shares": 500, "cost": 20, "current_price": 22, "sector_code": "S1", "sector_name": "化学制品", "stock_role": "CATCH_UP", "final_execution_label": "OVERHEATED_NO_CHASE", "holding_label": "REDUCE_PROFIT_PROTECTION", "sector_cycle": "CLIMAX", "sector_aux_labels": ["CLIMAX_FADING_RISK"], "sector_confidence": "HIGH"},
            ],
            "candidates": [
                {"ts_code": "C1", "name": "新试错", "sector_code": "S2", "sector_name": "物流", "stock_role": "CAPACITY_CORE", "final_execution_label": "READY_TRIAL", "sector_cycle": "STARTING", "sector_aux_labels": ["STRUCTURAL_START"], "sector_confidence": "MEDIUM"},
            ],
            "expected": "不能盯盘自动降低总仓位、单票和板块上限，限制新买。",
        },
    ]


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    lines = [
        "# 账户级仓位管理 MVP 小样本验证",
        "",
        "- 本验证只测试账户层风险控制，不修改评分权重。",
        "- 本验证不重跑原七题，不做自动交易。",
        "",
    ]
    for case in case_payloads():
        decision = decide_account_position(
            total_asset=case["total_asset"],
            cash=case["cash"],
            holdings=[holding_from_dict(x) for x in case["holdings"]],
            candidates=[candidate_from_dict(x) for x in case["candidates"]],
            market_weather=case["market_weather"],
            can_watch=case["can_watch"],
        )
        payload = decision_to_dict(decision)
        rows.append({"title": case["title"], "expected": case["expected"], "result": payload})
        lines.extend([
            f"## {case['title']}",
            f"- 预期验证点：{case['expected']}",
            f"- 账户总资产：{payload['total_asset']:.2f}",
            f"- 现金：{payload['cash']:.2f}",
            f"- 当前总仓位：{payload['total_position_pct']:.2f}%",
            f"- 总仓位上限：{payload['total_position_limit_pct']:.2f}%",
            f"- 账户风险标签：{' / '.join(payload['risk_labels'])}",
            f"- 是否允许新增买入：{'是' if payload['allow_new_buy'] else '否'}",
            f"- 新增总额度：{payload['allowed_new_total_value']:.2f}",
            f"- 是否需要降仓：{'是' if payload['need_reduce'] else '否'}",
            f"- 账户建议：{payload['account_advice']}",
            "",
        ])
    REPORT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"markdown": str(REPORT_MD), "json": str(REPORT_JSON), "cases": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
