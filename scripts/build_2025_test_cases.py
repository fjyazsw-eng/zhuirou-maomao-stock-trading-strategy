from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path


REQUIRED_DAILY_OUTPUTS = [
    "action: BUY / HOLD / REDUCE / SELL / WAIT",
    "reason",
    "buy_condition",
    "sell_condition",
    "stop_loss",
    "profit_protection",
    "normal_pullback_condition",
    "sector_retreat_condition",
    "max_position",
    "account_risk",
    "next_review_date",
]


def trading_days(conn: sqlite3.Connection, start: str, end: str, limit: int | None = None) -> list[str]:
    rows = conn.execute(
        "select cal_date from trade_cal where is_open=1 and cal_date between ? and ? order by cal_date",
        (start, end),
    ).fetchall()
    days = [r[0] for r in rows]
    return days[:limit] if limit else days


def case_by_id(cases: list[dict], test_id: str) -> dict:
    for case in cases:
        if case["test_id"] == test_id:
            return case
    raise KeyError(test_id)


def brief_symbols(case: dict, n: int = 3) -> list[dict]:
    return [
        {
            "ts_code": item["ts_code"],
            "name": item["name"],
            "industry": item["industry"],
            "role_hint_for_test": item.get("role_hint_for_test", "角色不确定"),
            "stage_a_close": item.get("stage_a_close"),
        }
        for item in case.get("target_symbols", [])[:n]
    ]


def validation_from_case(case: dict) -> dict:
    summary = case.get("stage_b_validation_summary", {})
    return {
        "final_return": summary.get("avg_stage_b_return_pct"),
        "max_drawdown": summary.get("worst_stage_b_max_drawdown_pct"),
        "trade_count": "待运行walk-forward后统计",
        "whether_profit_protected": "待运行walk-forward后统计",
        "whether_loss_controlled": "待运行walk-forward后统计",
        "whether_overtraded": "待运行walk-forward后统计",
        "whether_future_leakage": "待运行walk-forward后检查",
        "validation_boundary": "这里只保留路径设计和阶段B摘要占位，不运行完整评分。",
    }


def daily_steps(days: list[str], mode: str, question: str) -> list[dict]:
    out = []
    for idx, day in enumerate(days, start=1):
        if idx == 1:
            q = question
        elif mode == "holding":
            q = "今天这样波动，是正常回调还是走坏？现在要不要卖、减仓、继续持有或保护利润？"
        elif mode == "intraday":
            q = "用日线OHLC近似检查：是否触及买入区间、止损、止盈或利润保护；若高低点同时触发，标记INTRADAY_SEQUENCE_UNKNOWN。"
        elif mode == "account":
            q = "根据账户总仓位、单票仓位和板块集中度，今天是否还能新买，是否要降风险？"
        else:
            q = "根据今天收盘后已发生数据，更新是否买入、继续等待、减仓、卖出或持有观察。"
        out.append(
            {
                "date": day,
                "available_data_until": day,
                "user_question": q,
                "required_model_outputs": REQUIRED_DAILY_OUTPUTS,
            }
        )
    return out


def make_path(
    conn: sqlite3.Connection,
    source_case: dict,
    path_id: str,
    path_name: str,
    path_type: str,
    mode: str,
    planned_trade_cash: int,
    total_assets: int,
    available_cash: int,
    holdings: list[dict],
    question: str,
    start_date: str | None = None,
    end_date: str | None = None,
    length: int = 10,
) -> dict:
    stage_b = source_case["stage_b_window"]
    start = start_date or stage_b["start"]
    end = end_date or stage_b["end"]
    days = trading_days(conn, start, end, limit=length)
    if not days:
        days = [source_case["as_of_date"]]
    return {
        "path_id": path_id,
        "path_name": path_name,
        "path_type": path_type,
        "source_test_id": source_case["test_id"],
        "source_test_name": source_case["test_name"],
        "start_date": days[0],
        "end_date": days[-1],
        "target_symbols": brief_symbols(source_case, 4),
        "target_sectors_or_groups": source_case.get("target_sectors_or_groups", []),
        "initial_user_state": {
            "total_assets": total_assets,
            "available_cash": available_cash,
            "planned_trade_cash": planned_trade_cash,
            "holdings": holdings,
            "can_watch_market": False,
        },
        "decision_frequency": "每日收盘后决策",
        "execution_rule": {
            "buy": "若给出买入区间，次日最低价触及则按买入价或次日开盘价加0.1%滑点模拟；未触及则继续观察。",
            "sell": "止损看当日最低价，利润保护看当日最高价或收盘；仅收盘走弱则次日开盘加0.1%滑点模拟卖出。",
            "intraday_conflict": "同一天最高价和最低价同时触发关键条件时，标记INTRADAY_SEQUENCE_UNKNOWN。",
        },
        "allowed_data_rule": "每个date只能读取available_data_until及以前数据；阶段B只用于最后验证，不能反改当天判断。",
        "daily_steps": daily_steps(days, mode, question),
        "stage_b_validation": validation_from_case(source_case),
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


QUESTION_PATH_KEYS = [
    "path_id",
    "path_name",
    "path_type",
    "start_date",
    "end_date",
    "target_symbols",
    "target_sectors_or_groups",
    "initial_user_state",
    "decision_frequency",
    "execution_rule",
    "allowed_data_rule",
    "daily_steps",
]


def split_question_path(path: dict) -> dict:
    question = {key: path[key] for key in QUESTION_PATH_KEYS}
    question["known_data_limitations"] = [
        "limit_list缺失，涨跌停判断降级",
        "suspend部分数据，仅辅助",
        "历史概念池未完成，行业字段不等同概念板块",
        "不使用新闻公告、盘口、分钟线",
    ]
    question["required_model_outputs"] = REQUIRED_DAILY_OUTPUTS
    question["model_visible"] = True
    question["contains_future_validation"] = False
    return question


def split_validation_path(path: dict) -> dict:
    return {
        "path_id": path["path_id"],
        "path_name": path["path_name"],
        "path_type": path["path_type"],
        "source_test_id": path.get("source_test_id"),
        "start_date": path["start_date"],
        "end_date": path["end_date"],
        "target_symbols": path.get("target_symbols", []),
        "stage_b_validation": path.get("stage_b_validation", {}),
        "model_visible": False,
        "contains_future_validation": True,
        "private_file_rule": "只给评分器使用，正式作答阶段不能提供给模型。",
    }


def md_table(paths: list[dict]) -> list[str]:
    lines = [
        "| 路径ID | 类型 | 名称 | 日期 | 来源题 | 标的数 |",
        "| -- | -- | -- | -- | -- | --: |",
    ]
    for path in paths:
        source_test_id = path.get("source_test_id", "-")
        lines.append(
            f"| {path['path_id']} | {path['path_type']} | {path['path_name']} | {path['start_date']} 至 {path['end_date']} | {source_test_id} | {len(path['target_symbols'])} |"
        )
    return lines


def build(args: argparse.Namespace) -> dict:
    root = Path.cwd()
    outdir = root / "reports" / "tests_2025"
    outdir.mkdir(parents=True, exist_ok=True)
    filled = json.loads(Path(args.filled_registry).read_text(encoding="utf-8"))
    cases = filled["cases"]
    conn = sqlite3.connect(args.db_path)

    single_ids = ["TC2025-A01", "TC2025-A03", "TC2025-G01"]
    single_cases = []
    for test_id in single_ids:
        case = case_by_id(cases, test_id)
        single_cases.append(
            {
                "test_id": case["test_id"],
                "test_name": case["test_name"],
                "test_type": "SINGLE_POINT_DIAGNOSIS",
                "diagnosis_focus": [
                    "大盘天气",
                    "板块周期",
                    "个股角色",
                    "执行标签",
                    "账户风险",
                ],
                "as_of_date": case["as_of_date"],
                "stage_a_window": case["stage_a_window"],
                "user_state": case["user_state"],
                "target_symbols": brief_symbols(case, 5),
                "target_sectors_or_groups": case.get("target_sectors_or_groups", []),
                "allowed_data_rule": "只能使用as_of_date及以前数据。",
            }
        )

    paths = [
        make_path(
            conn,
            case_by_id(cases, "TC2025-A02"),
            "WF2025-PRE-01",
            "周末/盘前结构性机会小仓试错路径",
            "PREMARKET_SELECTION",
            "pre_market",
            10000,
            50000,
            50000,
            [],
            "我现在空仓，有10000元，下周可以买什么？请给买入条件、价格区间、仓位、止损和利润保护。",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-E01"),
            "WF2025-PRE-02",
            "非主线结构机会观察仓路径",
            "PREMARKET_SELECTION",
            "pre_market",
            10000,
            50000,
            50000,
            [],
            "非全面强势环境下，我空仓有10000元，是否允许观察仓或小试错？",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-A04"),
            "WF2025-PRE-03",
            "高位强势但可能继续上涨的风控路径",
            "PREMARKET_SELECTION",
            "pre_market",
            10000,
            50000,
            50000,
            [],
            "候选股高位但可能继续上涨，空仓是否追，还是等回踩确认？",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-B01"),
            "WF2025-HOLD-01",
            "浮盈3到8%利润保护跟踪路径",
            "HOLDING_TRACKING",
            "holding",
            10000,
            55000,
            40000,
            brief_symbols(case_by_id(cases, "TC2025-B01"), 1),
            "已有持仓浮盈3%到8%，今天是否继续持有、减仓还是设置利润保护线？",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-B02"),
            "WF2025-HOLD-02",
            "浮盈超过8%高位分歧跟踪路径",
            "HOLDING_TRACKING",
            "holding",
            10000,
            60000,
            35000,
            brief_symbols(case_by_id(cases, "TC2025-B02"), 1),
            "已有8%以上浮盈且高位波动，是否保护利润、减仓或继续拿核心？",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-C02"),
            "WF2025-HOLD-03",
            "浮亏超过6%弱结构止损跟踪路径",
            "HOLDING_TRACKING",
            "holding",
            10000,
            50000,
            25000,
            brief_symbols(case_by_id(cases, "TC2025-C02"), 1),
            "持仓浮亏超过6%且结构转弱，今天是正常回调还是逻辑走坏？是否退出？",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-A03"),
            "WF2025-INTRA-01",
            "高位强势股日线OHLC触发模拟路径",
            "INTRADAY_OHLC_TRIGGER",
            "intraday",
            10000,
            50000,
            50000,
            [],
            "用日线OHLC近似判断次日是否触及买入区间、止损或利润保护。",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-D01"),
            "WF2025-INTRA-02",
            "高潮退潮日线OHLC触发模拟路径",
            "INTRADAY_OHLC_TRIGGER",
            "intraday",
            10000,
            60000,
            30000,
            brief_symbols(case_by_id(cases, "TC2025-D01"), 1),
            "强势股连续上涨后，用日线OHLC近似验证止盈、止损和退潮信号触发。",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-G01"),
            "WF2025-ACC-01",
            "同板块集中账户降风险路径",
            "ACCOUNT_FULL_PATH",
            "account",
            10000,
            50000,
            15000,
            brief_symbols(case_by_id(cases, "TC2025-G01"), 3),
            "账户已有多只同组持仓，总仓位和集中度偏高，是否还能新买，是否要降风险？",
        ),
        make_path(
            conn,
            case_by_id(cases, "TC2025-F01"),
            "WF2025-ACC-02",
            "空仓到买入再到保护/退出完整账户路径",
            "ACCOUNT_FULL_PATH",
            "account",
            10000,
            50000,
            50000,
            [],
            "从空仓开始，连续10个交易日滚动判断何时观察、小仓、确认、保护利润、减仓或退出。",
        ),
    ]
    conn.close()

    registry = {
        "registry_name": "2025 多题测试集 V1（真实操盘路径模拟优先）",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "database_path": args.db_path,
        "integrity_status": "PASS_WITH_WARNINGS",
        "test_direction": "单点测试题 + 滚动式模拟实盘路径题；Walk-forward Trading Simulation 为后续主要检验方式。",
        "boundaries": [
            "不运行完整模型评分",
            "不修改评分权重",
            "不重跑原七题",
            "不自动交易",
            "不接真实账户",
            "不依赖完整limit_list",
            "不依赖完整suspend",
            "不把选题结果说成模型有效性证明",
        ],
        "single_point_cases": single_cases,
        "walk_forward_path_count": len(paths),
        "walk_forward_path_ids": [p["path_id"] for p in paths],
    }
    paths_obj = {
        "generated_at": registry["generated_at"],
        "file_warning": "DO_NOT_FEED_TO_MODEL_FOR_ANSWERING",
        "warning_detail": "该文件包含阶段B验证摘要，只用于审查和评分准备，不能作为正式作答输入。",
        "model_visible": False,
        "contains_future_validation": True,
        "database_path": args.db_path,
        "default_execution": {
            "initial_cash": 50000,
            "planned_trade_cash": 10000,
            "can_watch_market": False,
            "decision_frequency": "每日收盘后决策",
            "trade_length": "5到10个交易日，第一版默认10个交易日",
            "slippage": "0.1%",
        },
        "allowed_data_rule": "每一天只能读取当天及以前数据；阶段B只能用于最终验证。",
        "paths": paths,
    }
    questions_obj = {
        "generated_at": registry["generated_at"],
        "file_role": "MODEL_VISIBLE_QUESTIONS_ONLY",
        "model_visible": True,
        "contains_future_validation": False,
        "usage_rule": "正式测试时只喂本文件给模型；每日作答只能读取当天及以前数据。",
        "database_path": args.db_path,
        "paths": [split_question_path(path) for path in paths],
    }
    validation_obj = {
        "generated_at": registry["generated_at"],
        "file_role": "VALIDATION_PRIVATE_FOR_SCORER_ONLY",
        "model_visible": False,
        "contains_future_validation": True,
        "usage_rule": "只给评分器使用，正式作答阶段不能提供给模型。",
        "paths": [split_validation_path(path) for path in paths],
    }

    registry_json = outdir / "test_case_registry_2025.json"
    registry_md = outdir / "test_case_registry_2025.md"
    paths_json = outdir / "walk_forward_paths_2025.json"
    paths_md = outdir / "walk_forward_paths_2025.md"
    questions_json = outdir / "walk_forward_paths_2025_questions.json"
    questions_md = outdir / "walk_forward_paths_2025_questions.md"
    validation_json = outdir / "walk_forward_paths_2025_validation_private.json"
    validation_md = outdir / "walk_forward_paths_2025_validation_private.md"
    report_md = outdir / "test_case_selection_report_2025.md"

    write_json(registry_json, registry)
    write_json(paths_json, paths_obj)
    write_json(questions_json, questions_obj)
    write_json(validation_json, validation_obj)

    registry_lines = [
        "# 2025 多题测试集 V1",
        "",
        f"- 生成时间：{registry['generated_at']}",
        "- 测试方向：单点测试题 + 滚动式模拟实盘路径题。",
        "- 后续重点：Walk-forward Trading Simulation，而不是单日涨跌预测。",
        "- 边界：不运行完整评分，不修改权重，不自动交易，不接真实账户。",
        "",
        "## 单点诊断题",
        "",
        "| 题号 | 名称 | as_of_date | 标的数 | 重点 |",
        "| -- | -- | -- | --: | -- |",
    ]
    for case in single_cases:
        registry_lines.append(
            f"| {case['test_id']} | {case['test_name']} | {case['as_of_date']} | {len(case['target_symbols'])} | 大盘/板块/角色/执行/账户 |"
        )
    registry_lines.extend(["", "## Walk-forward 路径题", ""])
    registry_lines.extend(md_table(paths))
    registry_md.write_text("\n".join(registry_lines), encoding="utf-8")

    path_lines = [
        "# 2025 Walk-forward 真实操盘路径题",
        "",
        "> DO_NOT_FEED_TO_MODEL_FOR_ANSWERING：该整合文件包含阶段B验证摘要，只用于审查和评分准备，不能作为正式作答输入。",
        "",
        "- 正式测试时只喂 `walk_forward_paths_2025_questions.json`。",
        "- `walk_forward_paths_2025_validation_private.json` 只能给评分器。",
        "- 包含 `stage_b_validation` 的文件不能喂给模型。",
        "- 每日作答仍然只能读取当天及以前数据。",
        "",
        "- 每日收盘后决策，次日开盘价模拟成交并加入0.1%滑点。",
        "- 每一天只能读取当天及以前数据。",
        "- 若日线最高价和最低价同时触发关键条件，标记 `INTRADAY_SEQUENCE_UNKNOWN`。",
        "- 结束后统计最终收益、最大回撤、交易次数、仓位变化和风控质量。",
        "",
    ]
    path_lines.extend(md_table(paths))
    for path in paths:
        path_lines.extend(
            [
                "",
                f"## {path['path_id']}｜{path['path_name']}",
                f"- 类型：{path['path_type']}",
                f"- 日期：{path['start_date']} 至 {path['end_date']}",
                f"- 来源题：{path['source_test_id']}｜{path['source_test_name']}",
                f"- 初始资金：{path['initial_user_state']['total_assets']}；计划单笔资金：{path['initial_user_state']['planned_trade_cash']}；不能盯盘：是",
                f"- 标的：{', '.join([s['ts_code'] + s['name'] for s in path['target_symbols']])}",
                "- 每日必须输出：action、reason、buy_condition、sell_condition、stop_loss、profit_protection、normal_pullback_condition、sector_retreat_condition、max_position、account_risk、next_review_date。",
            ]
        )
    paths_md.write_text("\n".join(path_lines), encoding="utf-8")

    question_lines = [
        "# 2025 Walk-forward 模型可见题目文件",
        "",
        "- 正式测试时只喂本文件给模型。",
        "- 本文件不包含 `stage_b_validation`、`final_return`、`max_drawdown` 或任何阶段B答案摘要。",
        "- 每日作答只能读取当天及以前数据。",
        "",
    ]
    question_lines.extend(md_table(questions_obj["paths"]))
    questions_md.write_text("\n".join(question_lines), encoding="utf-8")

    validation_lines = [
        "# 2025 Walk-forward 私有验证文件",
        "",
        "- 只给评分器使用，正式作答阶段不能提供给模型。",
        "- 本文件包含阶段B验证摘要和后续验证占位。",
        "",
    ]
    validation_lines.extend(md_table(validation_obj["paths"]))
    validation_lines.append("")
    validation_lines.append("| 路径ID | final_return | max_drawdown |")
    validation_lines.append("| -- | --: | --: |")
    for path in validation_obj["paths"]:
        v = path["stage_b_validation"]
        validation_lines.append(f"| {path['path_id']} | {v.get('final_return')} | {v.get('max_drawdown')} |")
    validation_md.write_text("\n".join(validation_lines), encoding="utf-8")

    report_lines = [
        "# 2025 测试题选样与路径构建报告",
        "",
        f"- 生成时间：{registry['generated_at']}",
        "- 本轮调整：从单点预测题为主，调整为真实操盘路径模拟优先。",
        f"- 单点诊断题数量：{len(single_cases)}",
        f"- Walk-forward路径题数量：{len(paths)}",
        "- 周末/盘前选股路径：3道",
        "- 持仓滚动跟踪路径：3道",
        "- 盘中触发模拟路径：2道（日线OHLC近似）",
        "- 账户级完整路径：2道",
        "- 未运行完整评分；未修改评分权重；未重跑原七题；未自动交易；未接真实账户。",
        "- 正式测试时只喂 `walk_forward_paths_2025_questions.json`。",
        "- `walk_forward_paths_2025_validation_private.json` 只能给评分器。",
        "- 包含 `stage_b_validation` 的整合文件不能喂给模型。",
        "- 每日作答仍然只能读取当天及以前数据。",
        "",
        "## 路径清单",
        "",
    ]
    report_lines.extend(md_table(paths))
    report_lines.extend(
        [
            "",
            "## 后续运行要求",
            "",
            "- 每个交易日按当日 as_of 截断数据。",
            "- 不允许用后续收益反改当天判断。",
            "- 不依赖完整 limit_list 和完整 suspend。",
            "- 本轮只是构建测试题和路径，不证明模型有效性。",
        ]
    )
    report_md.write_text("\n".join(report_lines), encoding="utf-8")

    pkg_dir = root / "reports" / "review_packages"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    zip_path = pkg_dir / f"walk_forward_test_cases_2025_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for path in [
            registry_json,
            registry_md,
            paths_json,
            paths_md,
            questions_json,
            questions_md,
            validation_json,
            validation_md,
            report_md,
            Path("scripts/build_2025_test_cases.py"),
        ]:
            z.write(path, arcname=str(path))

    return {
        "registry_json": str(registry_json),
        "registry_md": str(registry_md),
        "paths_json": str(paths_json),
        "paths_md": str(paths_md),
        "questions_json": str(questions_json),
        "questions_md": str(questions_md),
        "validation_json": str(validation_json),
        "validation_md": str(validation_md),
        "selection_report": str(report_md),
        "review_package": str(zip_path),
        "single_point_cases": len(single_cases),
        "walk_forward_paths": len(paths),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--filled-registry", default="reports/tests_2025/test_case_registry_2025_filled.json")
    parser.add_argument("--db-path", default="D:/股票AI交易助手数据/sqlite/market_2025.sqlite")
    args = parser.parse_args()
    print(json.dumps(build(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
