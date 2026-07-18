from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.holding_management import decide_holding_from_dict


REPORT_DIR = ROOT / "reports" / "holding"
REPORT_PATH = REPORT_DIR / "holding_mvp_validation_20260704.md"
JSON_PATH = REPORT_DIR / "holding_mvp_validation_20260704.json"


CASES: list[dict[str, Any]] = [
    {
        "title": "样本1A：浮盈5%左右，海晨股份",
        "ts_code": "300873.SZ",
        "name": "海晨股份",
        "cost": 28.50,
        "current_price": 30.01,
        "original_status": "WAIT_PULLBACK_CORE",
        "final_execution_label": "OBSERVE_ONLY",
        "sector_cycle": "UNKNOWN",
        "sector_aux_labels": ["STRUCTURAL_START"],
        "sector_confidence": "LOW",
        "can_watch": True,
        "stock_role": "趋势核心",
        "expected": "不加仓，进入利润保护，受低置信度影响。",
    },
    {
        "title": "样本1B：浮盈5%左右，申通快递",
        "ts_code": "002468.SZ",
        "name": "申通快递",
        "cost": 15.80,
        "current_price": 16.61,
        "original_status": "WAIT_PULLBACK_CORE",
        "final_execution_label": "OBSERVE_ONLY",
        "sector_cycle": "UNKNOWN",
        "sector_aux_labels": [],
        "sector_confidence": "LOW",
        "can_watch": True,
        "stock_role": "角色不确定",
        "expected": "不加仓，已有浮盈按保护线处理。",
    },
    {
        "title": "样本2：浮盈10%以上，后排补涨",
        "ts_code": "TEST001.SZ",
        "name": "模拟后排补涨",
        "cost": 10.00,
        "current_price": 11.20,
        "original_status": "WAIT_CONFIRM",
        "final_execution_label": "OVERHEATED_NO_CHASE",
        "sector_cycle": "CLIMAX",
        "sector_aux_labels": ["CLIMAX_FADING_RISK"],
        "sector_confidence": "HIGH",
        "can_watch": True,
        "stock_role": "后排或弱结构",
        "expected": "强制利润保护，后排优先减仓。",
    },
    {
        "title": "样本3：浮亏-4%左右",
        "ts_code": "TEST002.SZ",
        "name": "模拟风险观察",
        "cost": 10.00,
        "current_price": 9.60,
        "original_status": "WAIT_CONFIRM",
        "final_execution_label": "WAIT_FOR_SUPPORT",
        "sector_cycle": "DIVERGENCE",
        "sector_aux_labels": ["WAIT_FOR_CONFIRMATION"],
        "sector_confidence": "MEDIUM",
        "can_watch": True,
        "stock_role": "趋势核心",
        "expected": "禁止补仓，等待承接，根据板块分歧降低风险。",
    },
    {
        "title": "样本4：浮亏-8%左右，后排弱结构",
        "ts_code": "TEST003.SZ",
        "name": "模拟弱结构亏损",
        "cost": 10.00,
        "current_price": 9.20,
        "original_status": "WEAK_STRUCTURE",
        "final_execution_label": "BREAKDOWN_AVOID",
        "sector_cycle": "FADING",
        "sector_aux_labels": [],
        "sector_confidence": "HIGH",
        "can_watch": True,
        "stock_role": "后排或弱结构",
        "expected": "触发止损或逻辑破坏判断，后排弱结构退出。",
    },
    {
        "title": "样本5：不能盯盘用户",
        "ts_code": "TEST004.SZ",
        "name": "模拟不能盯盘",
        "cost": 10.00,
        "current_price": 10.60,
        "original_status": "READY_CONFIRM",
        "final_execution_label": "READY_TRIAL",
        "sector_cycle": "STARTING",
        "sector_aux_labels": ["STRUCTURAL_START"],
        "sector_confidence": "MEDIUM",
        "can_watch": False,
        "stock_role": "容量核心",
        "expected": "自动降风险，不给加仓。",
    },
]


def fmt_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}%"


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    lines = [
        "# 持仓管理与利润保护模块 MVP 小样本验证",
        "",
        "- 本验证只测试持仓处理规则，不修改评分权重。",
        "- 本验证不重跑原七题，不做自动交易。",
        "",
    ]
    for case in CASES:
        result = decide_holding_from_dict(case)
        row = {
            "title": case["title"],
            "ts_code": case["ts_code"],
            "name": case["name"],
            "expected": case["expected"],
            "holding_label": result.holding_label,
            "pnl_pct": result.pnl_pct,
            "continue_hold": result.continue_hold,
            "reduce_position": result.reduce_position,
            "exit_position": result.exit_position,
            "allow_add": result.allow_add,
            "suggested_retain_pct": result.suggested_retain_pct,
            "profit_protection_line": result.profit_protection_line,
            "stop_loss_line": result.stop_loss_line,
            "main_reasons": result.main_reasons,
        }
        rows.append(row)
        lines.extend(
            [
                f"## {case['title']}",
                f"- 股票：{case['name']} {case['ts_code']}",
                f"- 预期验证点：{case['expected']}",
                f"- 当前浮盈浮亏：{fmt_pct(result.pnl_pct)}",
                f"- 持仓处理标签：{result.holding_label}（{result.holding_label_name}）",
                f"- 继续持有：{'是' if result.continue_hold else '否'}；减仓：{'是' if result.reduce_position else '否'}；退出：{'是' if result.exit_position else '否'}；允许加仓：{'是' if result.allow_add else '否'}",
                f"- 建议保留仓位：当前仓位的 {result.suggested_retain_pct}%以内",
                f"- 利润保护线：{result.profit_protection_line}",
                f"- 止损线：{result.stop_loss_line}",
                f"- 主要原因：{'；'.join(result.main_reasons)}",
                "",
            ]
        )
    JSON_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"markdown": str(REPORT_PATH), "json": str(JSON_PATH)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
