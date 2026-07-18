from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUT_DIR = REPORTS / "conversation"
DOCS = ROOT / "docs"


def read_text(path: Path, limit: int = 2400) -> str:
    if not path.exists():
        return "缺失"
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:limit]


def read_legend() -> str:
    path = DOCS / "评分怎么用.md"
    return read_text(path, 1800) if path.exists() else ""


def guided_prompt() -> str:
    path = DOCS / "飞书问答模板.md"
    return read_text(path, 1800) if path.exists() else ""


def classify_intent(question: str) -> str:
    text = question or ""
    if any(k in text for k in ["空仓", "没仓", "资金", "现金"]):
        return "empty"
    if any(k in text for k in ["持仓", "仓位", "减仓", "加仓"]):
        return "holding"
    if any(k in text for k in ["板块", "半导体", "电子化学品", "光学光电子", "物流"]):
        return "sector"
    return "single"


def has_horizon(question: str) -> bool:
    text = question or ""
    return any(k in text for k in ["短线", "中线", "长线", "波段", "隔日", "日内", "5日", "五日", "一周", "1周"])


def has_holding_detail(question: str, holdings: str) -> bool:
    text = f"{question or ''} {holdings or ''}"
    has_code = any(ch.isdigit() for ch in text) and len([ch for ch in text if ch.isdigit()]) >= 6
    has_cost = any(k in text for k in ["成本", "本钱", "买入价", "持仓价"])
    has_amount = any(k in text for k in ["股", "手", "仓位", "数量"])
    return bool(holdings) or (has_code and (has_cost or has_amount))


def has_holding_action(question: str) -> bool:
    text = question or ""
    return any(k in text for k in ["减仓", "加仓", "持有", "清仓", "卖", "走", "止损", "止盈", "处理", "怎么办", "要不要"])


def guidance_for_question(question: str, cash: float | None, holdings: str) -> list[str]:
    intent = classify_intent(question)
    prompts: list[str] = []
    if intent == "empty":
        if cash is None:
            prompts.append("请补充你的资金量，比如 50000 或 10 万。")
        if not has_horizon(question):
            prompts.append("请补充你想看短线、中线还是长线。")
    elif intent == "holding":
        if not has_holding_detail(question, holdings):
            prompts.append("请补充持仓代码、数量、成本，比如 002468:1000:15.8。")
        if not has_holding_action(question):
            prompts.append("请说明你更想看减仓、加仓还是继续持有。")
    elif intent == "sector":
        prompts.append("请补充你想问的板块名称和时间范围，比如 1 天、5 天或 20 天。")
    else:
        prompts.append("请补充股票代码，或直接说你是想低吸、追高还是观察。")
    return prompts


def answer(question: str, cash: float | None = None, holdings: str = "") -> str:
    latest = read_text(REPORTS / "latest_market_decision_report.md", 1600)
    enhanced = read_text(REPORTS / "enhanced" / "event_funds_state_20260702.md", 1200)
    events = read_text(REPORTS / "events" / "event_layer_20260702.md", 1200)
    advice = read_text(REPORTS / "advice" / "position_advice_20260702.md", 1200)
    lines = [
        "# 对话分析结果",
        "",
        f"## 用户问题",
        question or "未填写",
        "",
        "## 用户输入",
        f"- 现金：{cash if cash is not None else '未提供'}",
        f"- 持仓：{holdings or '未提供'}",
        "",
        "## 模型参考",
        "- 当前回答基于本地模型报告、事件面代理、资金代理和持仓建议。",
        "- 不替代最终交易决策，不自动下单。",
        "",
        "## 评分怎么用",
        read_legend() or "评分说明缺失",
        "",
        "## 飞书提问模板",
        guided_prompt() or "提问模板缺失",
        "",
        "## 这次提问还差什么",
        *([f"- {x}" for x in guidance_for_question(question, cash, holdings)] or ["- 信息已够用"]),
        "",
        "## 关键依据摘录",
        latest,
        "",
        "## 事件与资金代理摘录",
        enhanced,
        "",
        "## 事件层摘录",
        events,
        "",
        "## 持仓/空仓建议摘录",
        advice,
        "",
        "## 回答框架",
    ]
    if cash is not None and not holdings:
        lines.extend(
            [
                "- 当前按空仓场景处理。",
                "- 先看市场天气是否允许进攻，再看强势街区是否延续，再看候选个股是否过热。",
                "- 若市场天气弱、事件面缺失、资金代理偏弱，则应以观察和等待确认为主。",
                "- 简单记：大盘 70+ 才舒服，板块 75+ 才更像主线，个股执行 78+ 才算能参与，K线低吸 70+ 才叫承接强。",
            ]
        )
    elif holdings:
        lines.extend(
            [
                "- 当前按持仓场景处理。",
                "- 先检查持仓所属街区状态，再看个股是否出现放量下跌、破位、过热或事件风险。",
                "- 对不同周期可拆成短线防守、中线观察、长线是否仍有主线逻辑。",
                "- 简单记：个股执行分 62 到 77 先等确认，50 到 61 偏弱，50 以下别急着低吸。",
            ]
        )
    else:
        lines.extend([f"- {x}" for x in guidance_for_question(question, cash, holdings)] or ["- 请补充信息后再问。"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local conversation entry for stock model")
    parser.add_argument("--question", default="")
    parser.add_argument("--cash", type=float, default=None)
    parser.add_argument("--holdings", default="")
    args = parser.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = answer(args.question, args.cash, args.holdings)
    out = OUT_DIR / "latest_answer.md"
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"output": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
