from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SCORES = ROOT / "data" / "processed" / "scores"
DECISIONS = ROOT / "data" / "processed" / "decisions"
SQLITE = ROOT / "data" / "sqlite" / "market_120d.sqlite"
CONFIG = ROOT / "config"
OUT_DIR = REPORTS / "workflow"


@dataclass
class CheckItem:
    layer: str
    name: str
    status: str
    evidence: str
    impact: str
    next_action: str


def latest_date_from_files(folder: Path, prefix: str, suffix: str = "") -> str:
    dates: list[str] = []
    if not folder.exists():
        return ""
    for path in folder.glob(f"{prefix}*{suffix}"):
        for part in path.stem.replace("-", "_").split("_"):
            if part.isdigit() and len(part) == 8:
                dates.append(part)
    return max(dates) if dates else ""


def file_status(path: Path, layer: str, name: str, impact: str, next_action: str) -> CheckItem:
    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        return CheckItem(layer, name, "OK", f"已生成：{path.name}，修改时间 {mtime}", impact, "保持每日更新")
    return CheckItem(layer, name, "缺失", f"未找到：{path}", impact, next_action)


def sqlite_latest(table: str, col: str = "trade_date") -> str:
    if not SQLITE.exists():
        return ""
    try:
        with sqlite3.connect(SQLITE) as conn:
            row = conn.execute(f'SELECT MAX({col}) FROM "{table}"').fetchone()
        return str(row[0]) if row and row[0] is not None else ""
    except Exception:
        return ""


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def mask_present(value: str) -> str:
    if not value:
        return "未配置"
    return f"已配置，长度 {len(value)}"


def telegram_llm_status() -> list[CheckItem]:
    path = CONFIG / "telegram_bot.json"
    cfg = load_json(path)
    telegram = cfg.get("telegram", {})
    llm = cfg.get("llm", {})
    items: list[CheckItem] = []
    if not cfg:
        items.append(
            CheckItem(
                "交互层",
                "Telegram 配置",
                "缺失",
                "未找到或无法解析 telegram_bot.json",
                "手机端双向问答不可用",
                "检查 config/telegram_bot.json",
            )
        )
        return items
    items.append(
        CheckItem(
            "交互层",
            "Telegram 双向入口",
            "OK" if telegram.get("enabled") and telegram.get("bot_token") else "待确认",
            f"enabled={telegram.get('enabled')}，bot_token={mask_present(str(telegram.get('bot_token', '')))}",
            "决定手机是否能收发问题",
            "保持监听进程运行；必要时重启 start_telegram_assistant.bat",
        )
    )
    items.append(
        CheckItem(
            "智能层",
            "国内大模型总结",
            "OK" if llm.get("enabled") and llm.get("api_key") else "降级可用",
            f"provider={llm.get('provider', '-')}, model={llm.get('model', '-')}, api_key={mask_present(str(llm.get('api_key', '')))}",
            "决定回答是规则摘要还是更自然的中文分析",
            "若效果不够好，优化检索材料和提示词，不直接让模型凭空判断",
        )
    )
    return items


def event_layer_status(path: Path) -> CheckItem:
    payload = load_json(path.with_suffix(".json"))
    if not path.exists():
        return CheckItem(
            "事件层",
            "结构化事件",
            "缺失",
            f"未找到：{path}",
            "政策、公告、业绩、新闻影响短线风险",
            "补充手工事件或接入公告/新闻源后运行 run_event_layer",
        )
    data_status = str(payload.get("data_status", ""))
    event_count = int(payload.get("event_count", 0) or 0)
    mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    if data_status == "NO_STRUCTURED_SOURCE" or event_count == 0:
        return CheckItem(
            "事件层",
            "结构化事件",
            "降级可用",
            f"已生成：{path.name}，但事件数量 {event_count}，状态 {data_status or '-'}，修改时间 {mtime}",
            "能明确标注事件缺失，但不能识别突发政策、公告、业绩、新闻",
            "优先接入手工事件表，再接 Tushare 公告/业绩或交易所公告",
        )
    return CheckItem(
        "事件层",
        "结构化事件",
        "OK",
        f"已生成：{path.name}，事件数量 {event_count}，状态 {data_status}，修改时间 {mtime}",
        "政策、公告、业绩、新闻可进入模型判断",
        "保持每日更新并核验来源",
    )


def funds_proxy_status(path: Path) -> CheckItem:
    if not path.exists():
        return CheckItem(
            "资金代理层",
            "事件/资金代理状态",
            "缺失",
            f"未找到：{path}",
            "无法判断成交额变化、放量下跌、板块成交占比",
            "运行 run_event_funds_state",
        )
    payload = load_json(path.with_suffix(".json"))
    market = payload.get("market_proxy", {})
    mtime = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    if not market:
        return CheckItem(
            "资金代理层",
            "事件/资金代理状态",
            "降级可用",
            f"已生成：{path.name}，但市场代理为空，修改时间 {mtime}",
            "只能看板块分数，资金辅助不足",
            "检查 SQLite daily/daily_basic 和 run_event_funds_state",
        )
    return CheckItem(
        "资金代理层",
        "事件/资金代理状态",
        "降级可用",
        f"已生成：{path.name}，含成交额、涨跌家数、放量下跌等代理指标，修改时间 {mtime}",
        "可做资金代理判断，但不是逐笔主力资金或真实净流入",
        "后续补融资余额、同口径板块资金、成交占比连续性",
    )


def workflow_checks(as_of: str) -> list[CheckItem]:
    items: list[CheckItem] = []
    sqlite_daily = sqlite_latest("daily")
    sqlite_basic = sqlite_latest("daily_basic")
    latest_score = latest_date_from_files(SCORES, "sector_scores_", "_calibrated.csv")
    latest_stock = latest_date_from_files(SCORES, "stock_scores_", ".csv")
    latest_decision = latest_date_from_files(DECISIONS, "decision_results_", ".csv")
    date = as_of or latest_score or sqlite_daily

    items.append(
        CheckItem(
            "数据层",
            "SQLite 日行情",
            "OK" if sqlite_daily else "缺失",
            f"daily={sqlite_daily or '-'}，daily_basic={sqlite_basic or '-'}",
            "所有价格、涨跌幅、成交额、换手率的基础",
            "运行数据更新脚本；若 Tushare 失败，先检查 token 和网络",
        )
    )
    items.append(
        CheckItem(
            "评分层",
            "板块评分",
            "OK" if latest_score else "缺失",
            f"最新板块评分日期：{latest_score or '-'}",
            "决定天气-街区里的街区强弱",
            "运行 run_score / run_hierarchy_report",
        )
    )
    items.append(
        CheckItem(
            "评分层",
            "个股评分",
            "OK" if latest_stock else "缺失",
            f"最新个股评分日期：{latest_stock or '-'}",
            "决定店铺候选和空仓/持仓建议质量",
            "运行 run_stock_score；扩大覆盖面时注意性能",
        )
    )
    items.append(
        CheckItem(
            "决策层",
            "决策结果",
            "OK" if latest_decision else "缺失",
            f"最新决策结果日期：{latest_decision or '-'}",
            "把分数翻译成等待确认、回踩、观察等执行状态",
            "运行 run_decision",
        )
    )

    items.extend(
        [
            file_status(
                REPORTS / "regime" / f"sector_regime_{date}.md",
                "状态层",
                "板块状态识别",
                "判断正常分歧、短期回调、转弱、退潮",
                "运行 run_regime_classifier",
            ),
            file_status(
                REPORTS / "alerts" / f"sector_alerts_{date}.md",
                "预警层",
                "退潮预警",
                "提示强势板块快速掉入弱势区，避免后知后觉",
                "运行 run_sector_alerts",
            ),
            funds_proxy_status(REPORTS / "enhanced" / f"event_funds_state_{date}.md"),
            event_layer_status(REPORTS / "events" / f"event_layer_{date}.md"),
            file_status(
                REPORTS / "kline" / f"kline_analysis_{date}.json",
                "K线层",
                "承接/低吸判断",
                "识别是否有分歧承接、弱修复、未见承接",
                "运行 run_kline_analysis",
            ),
            file_status(
                REPORTS / "latest_market_decision_report.md",
                "报告层",
                "总览报告",
                "给网页、飞书、Telegram、人工复盘共同使用",
                "运行 run_hierarchy_report",
            ),
        ]
    )
    items.extend(telegram_llm_status())
    return items


def score_status(items: list[CheckItem]) -> dict[str, Any]:
    weights = {"OK": 1.0, "降级可用": 0.65, "待确认": 0.45, "缺失": 0.0}
    total = sum(weights.get(item.status, 0.0) for item in items)
    score = round(total / len(items) * 100, 1) if items else 0.0
    blockers = [item for item in items if item.status == "缺失"]
    downgraded = [item for item in items if item.status in {"降级可用", "待确认"}]
    if score >= 85 and not blockers:
        grade = "可用"
    elif score >= 65:
        grade = "可用但需补强"
    else:
        grade = "不适合依赖"
    return {"workflow_score": score, "grade": grade, "missing_count": len(blockers), "downgraded_count": len(downgraded)}


def model_shortcomings(items: list[CheckItem]) -> list[str]:
    notes = [
        "事件面仍是最大短板：没有公告/新闻源时，只能明确说未结构化，不能让模型凭空判断突发利好利空。",
        "资金面目前以可核验代理指标为主：成交额、放量下跌、板块成交占比、涨跌家数；不是逐笔主力资金。",
        "状态管理已经能区分短期回调/转弱/退潮，但需要每天持续生成，不能只看单日静态分数。",
        "智能总结层只能重组证据，不能代替数据层；如果检索材料缺失，回答会变笨或偏空泛。",
    ]
    if any(item.layer == "事件层" and item.status == "缺失" for item in items):
        notes.insert(0, "当前事件层报告缺失，会影响政策、公告、业绩、突发新闻判断。")
    if any(item.layer == "K线层" and item.status == "缺失" for item in items):
        notes.insert(0, "当前K线承接报告缺失，会影响低吸/承接类问题。")
    return notes


def write_report(as_of: str = "") -> dict[str, str]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    items = workflow_checks(as_of)
    summary = score_status(items)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "generated_at": now,
        "as_of": as_of or latest_date_from_files(SCORES, "sector_scores_", "_calibrated.csv") or sqlite_latest("daily"),
        "summary": summary,
        "checks": [asdict(item) for item in items],
        "shortcomings": model_shortcomings(items),
    }
    json_path = OUT_DIR / "latest_workflow_status.json"
    md_path = OUT_DIR / "latest_workflow_status.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 模型与工作流状态",
        "",
        f"- 生成时间：{now}",
        f"- 数据日期：{payload['as_of']}",
        f"- 工作流评分：{summary['workflow_score']} / 100",
        f"- 状态：{summary['grade']}",
        f"- 缺失项：{summary['missing_count']}，降级项：{summary['downgraded_count']}",
        "",
        "## 检查项",
        "| 层级 | 项目 | 状态 | 证据 | 影响 | 下一步 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in items:
        lines.append(
            f"| {item.layer} | {item.name} | {item.status} | {item.evidence.replace('|', '/')} | {item.impact.replace('|', '/')} | {item.next_action.replace('|', '/')} |"
        )
    lines.extend(["", "## 第三人视角短板"])
    for note in payload["shortcomings"]:
        lines.append(f"- {note}")
    lines.extend(
        [
            "",
            "## 下一步优先级",
            "1. 先保证每日数据、评分、状态、预警、K线报告都生成。",
            "2. 再补事件源：手工事件模板 -> Tushare公告/业绩 -> 交易所/巨潮公告。",
            "3. 再优化问答检索：先找证据，再让大模型总结，避免只靠大模型发挥。",
            "4. 最后做定时任务：盘后简报、退潮预警、用户点问三条线分开。",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="检查模型与工作流状态")
    parser.add_argument("--as-of", default="")
    args = parser.parse_args(argv)
    paths = write_report(args.as_of)
    print(json.dumps(paths, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
