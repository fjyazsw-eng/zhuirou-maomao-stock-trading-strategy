from __future__ import annotations

from typing import Any


VALIDATION_TYPES = (
    "风险判断有效",
    "等待建议有效",
    "机会识别有效",
    "利润保护有效",
    "过度保守",
    "标签过粗",
    "数据不足",
    "判断失效",
    "无法验证",
    "正常概率误差",
)


def validate_stage_b(stage_a: dict[str, Any], stage_b: dict[str, Any]) -> dict[str, Any]:
    main = stage_a.get("cycle_result", {}).get("main_label", "UNKNOWN")
    aux = stage_a.get("cycle_result", {}).get("auxiliary_labels", [])
    advice = stage_a.get("cycle_result", {})
    sector_ret = stage_b.get("sector_actual_performance", {}).get("等权涨跌幅%")
    if not stage_b.get("valid", True):
        return {
            "validation_type": "数据不足",
            "validation_note": "阶段B本身不可验证。",
            "needs_label_fix": False,
            "needs_advice_fix": False,
            "exposes_gap": True,
        }
    if sector_ret is None:
        return {
            "validation_type": "无法验证",
            "validation_note": "阶段B没有可用收益结果。",
            "needs_label_fix": False,
            "needs_advice_fix": False,
            "exposes_gap": True,
        }

    core_eff = stage_b.get("leader_validation", {}).get("是否整体继续有效")
    buy_allowed = "观察仓" in (advice.get("empty_advice") or "") or "试错" in (advice.get("empty_advice") or "") or "小仓" in (advice.get("empty_advice") or "")
    hold_protect = "保护" in (advice.get("holding_advice") or "") or "减仓" in (advice.get("holding_advice") or "")
    waiting = "等待" in (advice.get("empty_advice") or "") or "确认" in (advice.get("empty_advice") or "")

    if main == "CLIMAX":
        if sector_ret <= 0:
            return {
                "validation_type": "风险判断有效",
                "validation_note": "高潮后回撤，风险提示成立。",
                "needs_label_fix": "CLIMAX_FADING_RISK" not in aux,
                "needs_advice_fix": False,
                "exposes_gap": False,
            }
        return {
            "validation_type": "正常概率误差",
            "validation_note": "高潮后仍可能短延续，不代表风险判断失效。",
            "needs_label_fix": False,
            "needs_advice_fix": False,
            "exposes_gap": False,
        }

    if main in {"UNKNOWN", "DIVERGENCE"}:
        if sector_ret <= 0:
            return {
                "validation_type": "等待建议有效",
                "validation_note": "等待承接后继续走弱，说明不急于参与是合理的。",
                "needs_label_fix": "WAIT_FOR_CONFIRMATION" not in aux and "HIGH_LEVEL_UNSTABLE" not in aux,
                "needs_advice_fix": False,
                "exposes_gap": False,
            }
        if sector_ret > 0 and any(x in aux for x in ["STRUCTURAL_START", "SHORT_REPAIR"]):
            return {
                "validation_type": "机会识别有效",
                "validation_note": "阶段B上涨，说明结构性机会存在，但标签可能偏粗。",
                "needs_label_fix": "STRUCTURAL_START" not in aux,
                "needs_advice_fix": False,
                "exposes_gap": False,
            }
        if sector_ret > 0:
            return {
                "validation_type": "过度保守",
                "validation_note": "阶段A偏保守，阶段B上涨，可能漏掉结构性机会。",
                "needs_label_fix": True,
                "needs_advice_fix": True,
                "exposes_gap": True,
            }

    if main in {"STARTING", "FERMENTING"}:
        if sector_ret > 0 and core_eff:
            return {
                "validation_type": "机会识别有效",
                "validation_note": "核心继续有效且阶段B上涨。",
                "needs_label_fix": False,
                "needs_advice_fix": False,
                "exposes_gap": False,
            }
        if sector_ret <= 0:
            return {
                "validation_type": "判断失效",
                "validation_note": "看强但后续走弱。",
                "needs_label_fix": True,
                "needs_advice_fix": True,
                "exposes_gap": True,
            }

    if main in {"FADING", "ENDED"}:
        if sector_ret <= 0:
            return {
                "validation_type": "风险判断有效",
                "validation_note": "退潮/结束判断得到后续弱势验证。",
                "needs_label_fix": False,
                "needs_advice_fix": False,
                "exposes_gap": False,
            }
        return {
            "validation_type": "正常概率误差",
            "validation_note": "退潮后仍可能出现反抽，不等于判断完全错。",
            "needs_label_fix": False,
            "needs_advice_fix": False,
            "exposes_gap": False,
        }

    if main == "REPAIR":
        if sector_ret > 0:
            return {
                "validation_type": "机会识别有效",
                "validation_note": "修复判断对应上涨。",
                "needs_label_fix": False,
                "needs_advice_fix": False,
                "exposes_gap": False,
            }
        return {
            "validation_type": "正常概率误差",
            "validation_note": "修复失败不奇怪，继续看承接即可。",
            "needs_label_fix": False,
            "needs_advice_fix": False,
            "exposes_gap": False,
        }

    if waiting and sector_ret <= 0:
        return {
            "validation_type": "等待建议有效",
            "validation_note": "等待确认后继续弱势，说明建议有效。",
            "needs_label_fix": False,
            "needs_advice_fix": False,
            "exposes_gap": False,
        }

    return {
        "validation_type": "正常概率误差",
        "validation_note": "当前样本可解释，但不足以下结论。",
        "needs_label_fix": False,
        "needs_advice_fix": False,
        "exposes_gap": False,
    }
