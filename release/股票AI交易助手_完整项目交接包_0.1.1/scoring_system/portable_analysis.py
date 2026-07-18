from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from scoring_system.project_paths import database_path


ROOT = Path(__file__).resolve().parents[1]


def analyze_request(payload: dict[str, Any]) -> dict[str, Any]:
    task = str(payload.get("task") or "")
    if task not in {"candidate_analysis", "holding_analysis"}:
        raise ValueError("task must be candidate_analysis or holding_analysis")
    db = database_path(ROOT)
    if not db.exists():
        return {
            "data_date": None,
            "data_completeness": "DATA_INSUFFICIENT",
            "stale": True,
            "market_weather": "数据不足",
            "sector_state": "数据不足",
            "stock_role": "数据不足",
            "funds_and_turnover": "数据不足",
            "fundamentals_summary": "数据不足",
            "main_risks": ["本地数据库不存在，未生成或伪造行情"],
            "conclusion": "观察 / 数据不足",
            "execution_conditions": "配置真实数据源并通过健康检查后重新分析",
            "invalidation_conditions": "当前数据不足，任何确定性买入结论均无效",
            "position_ceiling": "0%",
            "protection_condition": "不执行新交易",
            "facts": [f"任务类型：{task}", f"检查时间：{datetime.now().isoformat(timespec='seconds')}"],
            "inferences": [],
        }
    return {
        "data_date": "available_in_local_database",
        "data_completeness": "READY_FOR_PROJECT_ANALYSIS",
        "stale": False,
        "market_weather": "请调用现有评分与报告模块",
        "sector_state": "请调用现有评分与报告模块",
        "stock_role": "请调用现有评分与报告模块",
        "funds_and_turnover": "请调用现有评分与报告模块",
        "fundamentals_summary": "需按输入标的读取",
        "main_risks": ["统一入口只负责调度，不改写核心评分逻辑"],
        "conclusion": "数据已就绪，交由现有分析模块处理",
        "execution_conditions": "运行日报或项目分析入口",
        "invalidation_conditions": "数据日期陈旧或字段缺失时降级",
        "position_ceiling": "由现有冻结规则决定",
        "protection_condition": "由现有冻结规则决定",
        "facts": [f"数据库存在：{db}"],
        "inferences": [],
    }


def load_input(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
