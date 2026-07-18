from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path


INDEX_CODES = ["000001.SH", "399001.SZ", "399006.SZ"]


def pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 2)


def qmarks(items: list[str]) -> str:
    return ",".join(["?"] * len(items))


def open_days(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    rows = conn.execute(
        "select cal_date from trade_cal where is_open=1 and cal_date between ? and ? order by cal_date",
        (start, end),
    ).fetchall()
    return [r[0] for r in rows]


def nearest_offsets(days: list[str]) -> dict[str, str]:
    if not days:
        return {}
    return {
        "d0": days[-1],
        "d5": days[max(0, len(days) - 5)],
        "d10": days[max(0, len(days) - 10)],
        "d20": days[max(0, len(days) - 20)],
        "amount5_start": days[max(0, len(days) - 5)],
        "amount_prev_start": days[max(0, len(days) - 20)],
        "amount_prev_end": days[max(0, len(days) - 6)],
    }


def index_summary(conn: sqlite3.Connection, start: str, end: str) -> str:
    days = open_days(conn, start, end)
    if len(days) < 2:
        return "指数数据不足"
    items: list[str] = []
    for code in INDEX_CODES:
        rows = conn.execute(
            "select trade_date, close from index_daily where ts_code=? and trade_date in (?,?) order by trade_date",
            (code, days[0], days[-1]),
        ).fetchall()
        if len(rows) == 2 and rows[0][1]:
            items.append(f"{code}阶段A涨跌幅{(rows[1][1] / rows[0][1] - 1) * 100:.2f}%")
    return "；".join(items) if items else "指数数据不足"


def metrics_for_window(conn: sqlite3.Connection, start: str, as_of: str) -> list[dict]:
    days = open_days(conn, start, as_of)
    if len(days) < 8:
        return []
    d = nearest_offsets(days)
    sql = f"""
    with base as (
      select d.ts_code, b.name, b.industry,
             max(case when d.trade_date=? then d.close end) as close0,
             max(case when d.trade_date=? then d.close end) as close5,
             max(case when d.trade_date=? then d.close end) as close10,
             max(case when d.trade_date=? then d.close end) as close20,
             avg(case when d.trade_date between ? and ? then d.amount end) as avg_amount_5d,
             avg(case when d.trade_date between ? and ? then d.amount end) as avg_amount_prev,
             avg(case when d.trade_date between ? and ? then d.close end) as ma20,
             max(case when d.trade_date between ? and ? then d.close end) as high20,
             min(case when d.trade_date between ? and ? then d.close end) as low20,
             count(case when d.trade_date between ? and ? then 1 end) as day_count
      from daily d
      join stock_basic b on d.ts_code=b.ts_code
      where d.trade_date between ? and ?
        and b.list_status='L'
        and b.name not like '%ST%'
      group by d.ts_code, b.name, b.industry
    )
    select * from base
    where close0 is not null and day_count >= 8 and avg_amount_5d > 50000
    """
    params = [
        d["d0"],
        d["d5"],
        d["d10"],
        d["d20"],
        d["amount5_start"],
        d["d0"],
        d["amount_prev_start"],
        d["amount_prev_end"],
        d["d20"],
        d["d0"],
        d["d20"],
        d["d0"],
        d["d20"],
        d["d0"],
        days[0],
        days[-1],
        days[0],
        days[-1],
    ]
    cols = [
        "ts_code",
        "name",
        "industry",
        "close0",
        "close5",
        "close10",
        "close20",
        "avg_amount_5d",
        "avg_amount_prev",
        "ma20",
        "high20",
        "low20",
        "day_count",
    ]
    out: list[dict] = []
    for row in conn.execute(sql, params).fetchall():
        r = dict(zip(cols, row))
        close0 = r["close0"]
        high20 = r["high20"]
        low20 = r["low20"]
        ma20 = r["ma20"]
        prev_amt = r["avg_amount_prev"] or r["avg_amount_5d"]
        r["ret_5d"] = close0 / r["close5"] - 1 if r["close5"] else None
        r["ret_10d"] = close0 / r["close10"] - 1 if r["close10"] else None
        r["ret_20d"] = close0 / r["close20"] - 1 if r["close20"] else None
        r["amount_ratio"] = r["avg_amount_5d"] / prev_amt if prev_amt else 1.0
        r["ma20_gap"] = close0 / ma20 - 1 if ma20 else 0.0
        r["position_20d"] = (close0 - low20) / (high20 - low20) if high20 and low20 and high20 > low20 else 0.5
        out.append(r)
    return out


def b_summary(conn: sqlite3.Connection, codes: list[str], as_of: str, start: str, end: str) -> dict[str, dict]:
    if not codes:
        return {}
    days = open_days(conn, start, end)
    if not days:
        return {}
    base_rows = conn.execute(
        f"select ts_code, close from daily where trade_date=? and ts_code in ({qmarks(codes)})",
        [as_of, *codes],
    ).fetchall()
    bases = {r[0]: r[1] for r in base_rows}
    rows = conn.execute(
        f"select ts_code, trade_date, close from daily where trade_date between ? and ? and ts_code in ({qmarks(codes)}) order by ts_code, trade_date",
        [days[0], days[-1], *codes],
    ).fetchall()
    grouped: dict[str, list[float]] = {}
    for code, _date, close in rows:
        grouped.setdefault(code, []).append(float(close))
    out: dict[str, dict] = {}
    for code, closes in grouped.items():
        base = bases.get(code)
        if not base or not closes:
            continue
        peak = float(base)
        max_dd = 0.0
        for close in closes:
            peak = max(peak, close)
            max_dd = min(max_dd, close / peak - 1)
        out[code] = {
            "stage_b_return_pct": round((closes[-1] / float(base) - 1) * 100, 2),
            "stage_b_max_drawdown_pct": round(max_dd * 100, 2),
            "stage_b_days": len(closes),
        }
    return out


def top(rows: list[dict], key, limit: int, reverse: bool = True) -> list[dict]:
    return sorted(rows, key=key, reverse=reverse)[:limit]


def select_case(conn: sqlite3.Connection, case: dict) -> tuple[list[dict], list[str], str, str]:
    cid = case["test_id"]
    aw = case["stage_a_window"]
    rows = metrics_for_window(conn, aw["start"], case["as_of_date"])
    if not rows:
        return [], [], "NEED_RESELECT", "阶段A数据不足。"

    def between(v, low, high):
        return v is not None and low <= v <= high

    reason = ""
    selected: list[dict] = []
    if cid == "TC2025-A01":
        selected = top([r for r in rows if between(r["ret_10d"], -0.08, 0.03) and r["position_20d"] < 0.65], lambda r: (-r["ret_10d"], r["avg_amount_5d"]), 5, reverse=False)
        reason = "短期偏弱或一般、位置不高，用于验证风险环境空仓等待。"
    elif cid == "TC2025-A02":
        selected = top([r for r in rows if r["ret_10d"] and 0.05 < r["ret_10d"] < 0.22 and r["amount_ratio"] > 1.05 and r["position_20d"] < 0.9], lambda r: (r["ret_10d"], r["amount_ratio"]), 5)
        reason = "近10日走强、成交温和放大，未选极端高位。"
    elif cid == "TC2025-A03":
        selected = top([r for r in rows if r["ret_10d"] and r["ret_10d"] > 0.18 and r["amount_ratio"] > 1.2 and r["position_20d"] > 0.8], lambda r: (r["ret_10d"], r["amount_ratio"]), 5)
        reason = "近10日大涨、成交放大且处于20日高位。"
    elif cid == "TC2025-B01":
        selected = top([r for r in rows if between(r["ret_10d"], 0.03, 0.08)], lambda r: r["avg_amount_5d"], 4)
        reason = "用10日前收盘模拟成本，阶段A浮盈约3%到8%。"
    elif cid == "TC2025-B02":
        selected = top([r for r in rows if r["ret_20d"] and r["ret_20d"] > 0.08 and r["ret_10d"] and r["ret_10d"] > 0.05 and r["position_20d"] > 0.75], lambda r: (r["ret_20d"], r["amount_ratio"]), 5)
        reason = "模拟浮盈超过8%，且位置偏高、量能变化明显。"
    elif cid == "TC2025-C01":
        selected = top([r for r in rows if between(r["ret_10d"], -0.06, -0.03) and r["ma20_gap"] < 0], lambda r: (r["ret_10d"], r["ma20_gap"]), 4, reverse=False)
        reason = "模拟浮亏3%到6%，且弱于20日均线。"
    elif cid == "TC2025-C02":
        selected = top([r for r in rows if r["ret_20d"] and r["ret_20d"] < -0.06 and r["ma20_gap"] < -0.03], lambda r: (r["ret_20d"], r["ma20_gap"]), 5, reverse=False)
        reason = "模拟浮亏超过6%，并有跌破20日趋势特征。"
    elif cid == "TC2025-D01":
        selected = top([r for r in rows if r["ret_20d"] and r["ret_20d"] > 0.18 and r["amount_ratio"] > 1.2 and r["position_20d"] > 0.85], lambda r: (r["ret_20d"], r["amount_ratio"]), 6)
        reason = "近20日强势、成交放大、短期乖离偏大。"
    elif cid == "TC2025-E01":
        selected = top([r for r in rows if r["ret_10d"] and r["ret_10d"] > 0.08 and r["ret_20d"] and r["ret_20d"] > 0.02 and 0.9 <= r["amount_ratio"] <= 2.5 and r["position_20d"] < 0.9], lambda r: (r["ret_10d"], r["amount_ratio"]), 5)
        reason = "非全面强势下，局部个股近10日转强且成交温和放大。"
    elif cid == "TC2025-F01":
        candidates = top([r for r in rows if r["ret_20d"] and r["ret_20d"] > 0.03 and r["amount_ratio"] > 0.9], lambda r: r["avg_amount_5d"], 600)
        b = b_summary(conn, [r["ts_code"] for r in candidates], case["as_of_date"], case["stage_b_window"]["start"], case["stage_b_window"]["end"])
        for r in candidates:
            r["b_dd"] = b.get(r["ts_code"], {}).get("stage_b_max_drawdown_pct")
        selected = top([r for r in candidates if r.get("b_dd") is not None and r["b_dd"] < -5], lambda r: (r["ret_20d"], r["amount_ratio"]), 4)
        reason = "阶段A已有一定强度，阶段B仅用于验证上涨后分歧/回撤路径。"
    elif cid == "TC2025-G01":
        sums: dict[str, float] = {}
        for r in rows:
            sums[r["industry"]] = sums.get(r["industry"], 0.0) + (r["avg_amount_5d"] or 0.0)
        industry = max(sums, key=sums.get)
        selected = top([r for r in rows if r["industry"] == industry], lambda r: r["avg_amount_5d"], 5)
        reason = f"构造同一行业集中账户，行业={industry}，用于账户集中风险验证。"
    elif cid == "TC2025-A04":
        candidates = top([r for r in rows if r["ret_10d"] and r["ret_10d"] > 0.10 and r["position_20d"] > 0.75], lambda r: r["avg_amount_5d"], 800)
        b = b_summary(conn, [r["ts_code"] for r in candidates], case["as_of_date"], case["stage_b_window"]["start"], case["stage_b_window"]["end"])
        for r in candidates:
            r["b_ret"] = b.get(r["ts_code"], {}).get("stage_b_return_pct")
        selected = top([r for r in candidates if r.get("b_ret") is not None and r["b_ret"] > 5], lambda r: (r["b_ret"], r["ret_10d"]), 5)
        reason = "短期强势且阶段B继续上涨，用作过度保守反例验证；不得反改阶段A。"

    if len(selected) < 2:
        return [], [], "NEED_RESELECT", reason + "；按当前条件未找到足够样本。"

    codes = [r["ts_code"] for r in selected]
    bs = b_summary(conn, codes, case["as_of_date"], case["stage_b_window"]["start"], case["stage_b_window"]["end"])
    targets: list[dict] = []
    for r in selected:
        role = "角色不确定"
        if r["avg_amount_5d"] >= sorted([x["avg_amount_5d"] for x in selected])[max(0, len(selected) - 2)]:
            role = "容量核心候选"
        if r["ret_10d"] and r["ret_10d"] > 0.18 and r["position_20d"] > 0.8:
            role = "高位强势/补涨候选"
        if r["ma20_gap"] < -0.03:
            role = "弱结构候选"
        targets.append(
            {
                "ts_code": r["ts_code"],
                "name": r["name"],
                "industry": r["industry"],
                "role_hint_for_test": role,
                "stage_a_close": round(float(r["close0"]), 2),
                "stage_a_ret_5d_pct": pct(r["ret_5d"]),
                "stage_a_ret_10d_pct": pct(r["ret_10d"]),
                "stage_a_ret_20d_pct": pct(r["ret_20d"]),
                "amount_ratio_5d_vs_prev_pct": round((r["amount_ratio"] - 1) * 100, 2),
                "position_20d": round(r["position_20d"], 2),
                "ma20_gap_pct": pct(r["ma20_gap"]),
                **bs.get(r["ts_code"], {}),
            }
        )
    return targets, sorted({t["industry"] for t in targets}), "FILLED", reason


def write_outputs(args: argparse.Namespace) -> dict:
    root = Path.cwd()
    outdir = root / "reports" / "tests_2025"
    outdir.mkdir(parents=True, exist_ok=True)

    registry = json.loads(Path(args.registry_json).read_text(encoding="utf-8"))
    # Explicitly read all attachments so the provenance is clear.
    Path(args.registry_md).read_text(encoding="utf-8")
    Path(args.prompt_md).read_text(encoding="utf-8")

    conn = sqlite3.connect(args.db_path)
    filled = registry.copy()
    filled["filled_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    filled["fill_status"] = "FILLED_BY_CODEX_FROM_D_DRIVE_SQLITE"
    filled["test_design_update"] = {
        "mode": "single_point_cases_plus_walk_forward_paths",
        "priority": "walk_forward_paths",
        "walk_forward_default": {
            "initial_cash": 50000,
            "initial_position": "empty",
            "can_watch_market": False,
            "length_trading_days": 10,
            "decision_frequency": "daily_after_close",
            "execution_rule": "next_open_with_0.1pct_slippage",
            "daily_data_boundary": "each day can only read that day and earlier data",
        },
    }
    need: list[str] = []
    for case in filled["cases"]:
        targets, sectors, status, reason = select_case(conn, case)
        case["fill_status"] = status
        if status == "NEED_RESELECT":
            need.append(case["test_id"])
        case["target_symbols"] = targets
        case["target_sectors_or_groups"] = sectors
        case["stage_a_data_summary"] = {
            "as_of_rule": "阶段A只使用as_of_date当日及以前数据。",
            "market_index_summary": index_summary(conn, case["stage_a_window"]["start"], case["as_of_date"]),
            "selection_rationale": reason,
            "data_limitations": "limit_list缺失，涨跌停判断降级；suspend部分数据，仅辅助；行业来自stock_basic.industry，不等同历史概念池。",
        }
        vals = [t.get("stage_b_return_pct") for t in targets if t.get("stage_b_return_pct") is not None]
        dds = [t.get("stage_b_max_drawdown_pct") for t in targets if t.get("stage_b_max_drawdown_pct") is not None]
        case["stage_b_validation_summary"] = {
            "validation_boundary": "阶段B只用于验证摘要，不能反改阶段A。",
            "target_count": len(targets),
            "avg_stage_b_return_pct": round(sum(vals) / len(vals), 2) if vals else None,
            "worst_stage_b_return_pct": min(vals) if vals else None,
            "worst_stage_b_max_drawdown_pct": min(dds) if dds else None,
            "validation_note": "未运行完整评分；仅形成后续封闭测试复盘所需价格摘要。",
        }
    conn.close()

    json_out = outdir / "test_case_registry_2025_filled.json"
    md_out = outdir / "test_case_registry_2025_filled.md"
    selection_out = outdir / "test_case_selection_report_2025.md"
    json_out.write_text(json.dumps(filled, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        "# 2025 多题测试集 V0 补齐版",
        "",
        f"- 生成时间：{filled['filled_at']}",
        f"- 数据库：`{args.db_path}`",
        "- 测试体系：单点测试题 + 滚动式模拟实盘路径题；后续以 Walk-forward 为主检验方式。",
        "- 边界：未运行完整评分，未修改评分权重，未自动交易，未接真实账户。",
        "- 数据限制：`limit_list` 缺失；`suspend` 部分数据；行业字段不等同历史概念池。",
        "",
        "## Walk-forward 后续测试原则",
        "",
        "- 初始资金：50000元；初始状态：空仓；不能盯盘。",
        "- 测试长度：默认10个交易日；每日收盘后决策；次日开盘价加0.1%滑点模拟成交。",
        "- 每天只能读取当天及以前数据；不得用后续收益反改当天判断。",
        "- 结束后统计收益、最大回撤、交易次数、仓位变化和风控质量。",
        "",
    ]
    for case in filled["cases"]:
        b = case["stage_b_validation_summary"]
        md_lines.extend(
            [
                f"## {case['test_id']}｜{case['test_name']}",
                f"- 填充状态：{case['fill_status']}",
                f"- 类型：{case['test_type']}",
                f"- as_of_date：{case['as_of_date']}",
                f"- 阶段A：{case['stage_a_window']['start']} 至 {case['stage_a_window']['end']}",
                f"- 阶段B：{case['stage_b_window']['start']} 至 {case['stage_b_window']['end']}",
                f"- 行业/组别：{', '.join(case['target_sectors_or_groups']) if case['target_sectors_or_groups'] else 'NEED_RESELECT'}",
                f"- 阶段A摘要：{case['stage_a_data_summary']['market_index_summary']}；{case['stage_a_data_summary']['selection_rationale']}",
                f"- 阶段B验证摘要：样本数 {b['target_count']}，平均收益 {b['avg_stage_b_return_pct']}%，最差收益 {b['worst_stage_b_return_pct']}%，最差回撤 {b['worst_stage_b_max_drawdown_pct']}%。",
                "",
                "| 代码 | 名称 | 行业 | 角色提示 | A收盘 | A_5日% | A_10日% | A_20日% | 量能变化% | 20日位置 | MA20偏离% | B收益% | B最大回撤% |",
                "| -- | -- | -- | -- | --: | --: | --: | --: | --: | --: | --: | --: | --: |",
            ]
        )
        for t in case["target_symbols"]:
            md_lines.append(
                f"| {t['ts_code']} | {t['name']} | {t['industry']} | {t['role_hint_for_test']} | {t['stage_a_close']} | {t.get('stage_a_ret_5d_pct')} | {t.get('stage_a_ret_10d_pct')} | {t.get('stage_a_ret_20d_pct')} | {t.get('amount_ratio_5d_vs_prev_pct')} | {t.get('position_20d')} | {t.get('ma20_gap_pct')} | {t.get('stage_b_return_pct')} | {t.get('stage_b_max_drawdown_pct')} |"
            )
        md_lines.append("")
    md_out.write_text("\n".join(md_lines), encoding="utf-8")

    report_lines = [
        "# 2025 测试题选样补齐报告",
        "",
        f"- 生成时间：{filled['filled_at']}",
        "- 本轮动作：读取3个附件，按 selection_rule 从 D 盘 SQLite 补齐具体股票、行业/板块、阶段A行情摘要、阶段B验证摘要。",
        "- 测试设计修正：后续不只做单点判断，增加滚动式模拟实盘路径题，并将 Walk-forward 作为主要检验方式。",
        "- 未做事项：未运行完整评分，未修改评分权重，未重跑原七题，未自动交易，未接真实账户。",
        "- 重要限制：limit_list 缺失，涨跌停判断降级；suspend 部分覆盖，停牌仅辅助；未使用历史概念池。",
        f"- NEED_RESELECT：{', '.join(need) if need else '无'}",
        "",
        "## Walk-forward 测试设计",
        "",
        "- 初始资金：50000元；初始空仓；不能盯盘。",
        "- 测试长度：5到10个交易日，第一版默认10个交易日。",
        "- 决策频率：每日收盘后决策。",
        "- 成交规则：次日开盘价模拟成交，加入0.1%滑点。",
        "- 每日数据边界：第N天只能读取第N天及以前数据。",
        "- 统计指标：最终收益、最大回撤、交易次数、仓位变化、风控质量、是否乱买、是否保护利润、是否控制亏损。",
        "",
        "| 题号 | 状态 | 样本数 | 行业/组别 | 阶段B平均收益% | 阶段B最差收益% | 阶段B最差回撤% |",
        "| -- | -- | --: | -- | --: | --: | --: |",
    ]
    for case in filled["cases"]:
        b = case["stage_b_validation_summary"]
        report_lines.append(
            f"| {case['test_id']} | {case['fill_status']} | {len(case['target_symbols'])} | {', '.join(case['target_sectors_or_groups'])} | {b['avg_stage_b_return_pct']} | {b['worst_stage_b_return_pct']} | {b['worst_stage_b_max_drawdown_pct']} |"
        )
    report_lines.extend(
        [
            "",
            "## 使用边界",
            "",
            "- 正式答题时，只能暴露阶段A窗口、as_of_date、用户状态、target_symbols和阶段A摘要。",
            "- 阶段B验证摘要只用于考后复盘，不得作为阶段A判断输入。",
            "- Walk-forward 执行时，每一天都必须重新按当日 as_of 截断数据。",
            "- 如果后续补齐 limit_list、suspend 或历史概念池，可生成 V1，但不能反改本版阶段A。",
        ]
    )
    selection_out.write_text("\n".join(report_lines), encoding="utf-8")

    pkg_dir = root / "reports" / "review_packages"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    zip_path = pkg_dir / f"test_case_registry_2025_fill_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for path in [
            json_out,
            md_out,
            selection_out,
            Path(args.registry_json),
            Path(args.registry_md),
            Path(args.prompt_md),
            Path("scripts/fill_2025_test_cases.py"),
        ]:
            z.write(path, arcname=f"reports/tests_2025/{path.name}" if path.parent == outdir else f"input_or_script/{path.name}")
    return {
        "json": str(json_out),
        "markdown": str(md_out),
        "selection_report": str(selection_out),
        "review_package": str(zip_path),
        "cases_total": len(filled["cases"]),
        "filled": len(filled["cases"]) - len(need),
        "need_reselect": need,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry-json", required=True)
    parser.add_argument("--registry-md", required=True)
    parser.add_argument("--prompt-md", required=True)
    parser.add_argument("--db-path", required=True)
    args = parser.parse_args()
    print(json.dumps(write_outputs(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
