from __future__ import annotations

import argparse
import json
from pathlib import Path

from scoring_system.network_quote_fallback import fetch_realtime_quote
from scoring_system.output_formatter import compact_table
from scoring_system.report_freshness import ensure_fresh_reports


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OUT_DIR = REPORTS / "conversation"
USER_CONTEXT_PATH = OUT_DIR / "user_context.json"


def read_text(path: Path, limit: int = 2400) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def load_user_context() -> dict[str, str]:
    if not USER_CONTEXT_PATH.exists():
        return {
            "last_scene": "",
            "last_stock": "",
            "default_horizon": "",
            "last_trade_date": "",
            "updated_at": "",
        }
    try:
        payload = json.loads(USER_CONTEXT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "last_scene": "",
            "last_stock": "",
            "default_horizon": "",
            "last_trade_date": "",
            "updated_at": "",
        }
    if not isinstance(payload, dict):
        return {
            "last_scene": "",
            "last_stock": "",
            "default_horizon": "",
            "last_trade_date": "",
            "updated_at": "",
        }
    return {
        "last_scene": str(payload.get("last_scene", "")),
        "last_stock": str(payload.get("last_stock", "")),
        "default_horizon": str(payload.get("default_horizon", "")),
        "last_trade_date": str(payload.get("last_trade_date", "")),
        "updated_at": str(payload.get("updated_at", "")),
    }


def save_user_context(payload: dict[str, str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    USER_CONTEXT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_lines(text: str, prefixes: list[str], limit: int = 3) -> list[str]:
    hits: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and any(line.startswith(prefix) for prefix in prefixes):
            hits.append(line)
        if len(hits) >= limit:
            break
    return hits


def read_tushare_status() -> dict[str, str]:
    path = REPORTS / "tushare" / "latest_tushare_status.json"
    if not path.exists():
        return {
            "status": "待确认",
            "endpoint": "-",
            "latest_trade_date": "-",
            "data_trade_date": "-",
            "message": "未检测到最近探针结果",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "status": "待确认",
            "endpoint": "-",
            "latest_trade_date": "-",
            "data_trade_date": "-",
            "message": "探针结果无法解析",
        }
    return {
        "status": str(payload.get("status", "待确认")),
        "endpoint": str(payload.get("endpoint", "-")),
        "latest_trade_date": str(payload.get("latest_trade_date", "-")),
        "data_trade_date": str(payload.get("data_trade_date", "-")),
        "message": str(payload.get("message", "")),
    }


def classify_question(question: str, holdings: str) -> str:
    text = f"{question or ''} {holdings or ''}"
    if any(k in text for k in ["推荐", "轻仓买入", "试仓", "能买什么", "可以买", "候选"]):
        return "candidates"
    if any(k in text for k in ["板块", "龙头", "核心", "补涨", "后排", "周期"]):
        return "sector"
    if any(k in text for k in ["持仓", "成本", "减仓", "加仓", "止损", "止盈", "清仓", "持有", "卖"]):
        return "holding"
    return "generic"


def extract_stock_code(text: str) -> str:
    raw = text or ""
    digits = []
    current = ""
    for ch in raw:
        if ch.isdigit():
            current += ch
        else:
            if len(current) >= 6:
                digits.append(current)
            current = ""
    if len(current) >= 6:
        digits.append(current)
    return digits[0][:6] if digits else ""


def fallback_quote_block(stock_code: str) -> str:
    try:
        quote = fetch_realtime_quote(stock_code)
    except Exception as exc:
        return "\n".join(
            [
                "联网补充",
                f"- 股票代码：{stock_code}",
                f"- 状态：联网补充失败",
                f"- 原因：{type(exc).__name__}: {str(exc)[:120]}",
            ]
        )
    return "\n".join(
        [
            "联网补充",
            f"- 股票：{quote['name']} {quote['ts_code']}",
            f"- 数据源：{quote['source']}",
            f"- 日期：{quote['trade_date']}",
            f"- 最新价：{quote['price']}",
            f"- 涨跌幅：{quote['pct_chg']}",
            f"- 开高低昨收：{quote['open']} / {quote['high']} / {quote['low']} / {quote['prev_close']}",
            f"- 成交额：{quote['amount']}",
        ]
    )


def extract_horizon(text: str) -> str:
    raw = text or ""
    for key in ["短线", "中线", "长线", "下一交易日", "今天", "波段"]:
        if key in raw:
            return key
    return ""


def needs_more_info(question: str, holdings: str, kind: str) -> list[str]:
    text = question or ""
    tips: list[str] = []
    if kind == "holding":
        has_code = any(ch.isdigit() for ch in f"{text} {holdings}") and len([ch for ch in f"{text} {holdings}" if ch.isdigit()]) >= 6
        if not has_code:
            tips.append("补股票代码")
        if not any(k in text for k in ["成本", "买入价"]) and "成本" not in holdings:
            tips.append("补持仓成本")
        if not any(k in text for k in ["仓位", "股", "手", "数量"]) and not holdings:
            tips.append("补持仓数量或仓位")
    if kind == "candidates" and not any(k in text for k in ["短线", "中线", "下一交易日", "今天"]):
        tips.append("补周期，比如短线或下一交易日")
    return tips


def report_snapshot() -> dict[str, str]:
    text = read_text(REPORTS / "latest_market_decision_report.md", 5000)
    weather = extract_lines(text, ["- 大盘天气评分", "- 上涨家数", "- 下跌家数", "- 今日成交"], 4)
    return {
        "weather": weather[0] if len(weather) > 0 else "大盘环境数据缺失",
        "up": weather[1] if len(weather) > 1 else "",
        "down": weather[2] if len(weather) > 2 else "",
        "turnover": weather[3] if len(weather) > 3 else "",
    }


def market_state_from_text(weather_line: str) -> str:
    line = weather_line or ""
    if "风险" in line or "偏弱" in line or "退潮" in line:
        return "弱"
    if "震荡" in line or "分化" in line:
        return "震荡"
    if "强" in line or "偏强" in line or "修复" in line:
        return "强"
    return "待确认"


def tushare_block(status: dict[str, str]) -> str:
    label = "正常" if status["status"] == "PASS" else "异常 / 待确认"
    return compact_table(
        "数据状态",
        [
            ("Tushare状态", label),
            ("最新交易日", status["latest_trade_date"]),
            ("行情落点", status["data_trade_date"]),
            ("接口地址", status["endpoint"]),
        ],
    )


def candidates_answer(question: str, market: dict[str, str], status: dict[str, str], tips: list[str]) -> str:
    state = market_state_from_text(market["weather"])
    can_try = "没有" if state in {"弱", "待确认"} else "有"
    lines = [
        "当前结论",
        f"今天 / 下一交易日可以轻仓试错：{can_try}",
        "",
        f"市场状态：{state}",
        market["weather"],
    ]
    if market["up"]:
        lines.append(market["up"])
    if market["down"]:
        lines.append(market["down"])
    lines.extend(
        [
            "",
            "推荐股票",
            "当前没有直接展开全市场候选，默认先按 指数 -> 板块 -> 细分方向 -> 核心股 的顺序筛。",
        ]
    )
    if state in {"弱", "待确认"}:
        lines.append("当前动作：先别买，新开仓优先等数据和板块承接确认。")
    else:
        lines.append("当前动作：只考虑核心股轻仓试错，不做后排，不开盘追高。")
    lines.extend(
        [
            "执行时间：优先等开盘后15到30分钟确认承接。",
            "止损/失效：跌破关键支撑且收不回，直接放弃。",
        ]
    )
    if tips:
        lines.append(f"补充信息：{'、'.join(tips)}。")
    lines.extend(
        [
            "",
            "一句话结论",
            "能试就轻仓试核心，条件不够就先别买，不为凑数量硬推。",
        ]
    )
    return "\n".join(lines)


def holding_answer(question: str, holdings: str, market: dict[str, str], tips: list[str]) -> str:
    lines = [
        "直接建议",
        "",
        "用户状态| 操作",
        "|---|---|",
        "空仓| 先别买",
        "已持仓| 先看强弱位，强就持有，转弱就轻减",
        "准备加仓| 不追高，等回踩确认",
        "准备卖出| 破位先减，反抽不强再卖",
        "",
        "执行条件",
        "",
        "- 买入条件：只在板块没退潮、个股回踩承接确认后考虑。",
        "- 减仓条件：跌破5日线不修复、放量滞涨、板块开始分化。",
        "- 止损条件：跌破关键支撑且收不回，直接执行。",
        "- 仓位上限：高位股半仓以下，普通试错20%以内。",
        "",
        "市场参考",
        market["weather"],
    ]
    if holdings:
        lines.append(f"持仓补充：{holdings}")
    if tips:
        lines.append(f"还缺：{'、'.join(tips)}。")
    lines.extend(
        [
            "",
            "最终一句话",
            "有利润先保护，转弱就减，别在高位硬扛。",
        ]
    )
    return "\n".join(lines)


def sector_answer(question: str, market: dict[str, str]) -> str:
    state = market_state_from_text(market["weather"])
    return "\n".join(
        [
            "板块结论",
            "",
            "项目| 结论",
            "|---|---|",
            f"当前周期| {'分化修复 / 震荡待确认' if state == '震荡' else '主升 / 修复待确认' if state == '强' else '弱势 / 退潮待确认'}",
            f"板块强度| {'中等' if state == '震荡' else '强' if state == '强' else '弱'}",
            "资金状态| 先看核心是否继续抱团，再看后排是否跟随",
            "核心股票| 需要结合用户指定板块再落到2到5只",
            "后排状态| 后排不能主动接飞刀",
            f"操作结论| {'可只看核心轻仓试错' if state == '强' else '先看不买，等分化后的承接确认' if state == '震荡' else '先回避'}",
            "",
            "一句话总结",
            "先判断板块是不是还在主线，再分龙头、核心、补涨、后排，不混着做。",
        ]
    )


def generic_answer(question: str, cash: float | None, market: dict[str, str], tips: list[str]) -> str:
    cash_text = f"{cash:,.0f} 元" if cash is not None else "未提供"
    lines = [
        "结论表",
        "",
        "项目| 结论",
        "|---|---|",
        f"问题类型| {classify_question(question, '')}",
        f"市场状态| {market_state_from_text(market['weather'])}",
        f"空仓建议| {'先别追，等承接确认' if market_state_from_text(market['weather']) != '强' else '只做核心轻仓试错'}",
        "持仓建议| 强就持有，弱就轻减，破位就走",
        "仓位建议| 单次轻仓为主，默认不超过20%-30%",
        "止损/减仓位| 跌破关键支撑且收不回就执行",
        "失效条件| 数据异常、板块退潮、个股破位",
        "",
        "一句话结论",
        "先看市场和板块，再看个股位置；能买就轻仓买核心，不行就先别买。",
        "",
        "下一步",
        f"- 资金信息：{cash_text}",
        f"- 市场参考：{market['weather']}",
    ]
    if tips:
        lines.append(f"- 还缺信息：{'、'.join(tips)}")
    return "\n".join(lines)


def answer(question: str, cash: float | None = None, holdings: str = "") -> str:
    ensure_fresh_reports()
    context = load_user_context()
    status = read_tushare_status()
    market = report_snapshot()
    kind = classify_question(question, holdings)
    tips = needs_more_info(question, holdings, kind)
    stock_code = extract_stock_code(f"{question} {holdings}") or context["last_stock"]
    horizon = extract_horizon(question) or context["default_horizon"]

    if status["status"] != "PASS":
        blocks = [
            tushare_block(status),
            "\n".join(
                [
                    "当前建议",
                    "先不做新的确定性买入判断，只处理已有风控。",
                    f"异常说明：{status['message'] or '优先怀疑 Tushare 接入或返回问题。'}",
                    "下一步",
                    "- 先跑一次 Tushare 探针确认 daily / daily_basic / trade_cal 是否完整。",
                    "- 数据恢复前，只保留止损、减仓、持有这类防守结论。",
                ]
            ),
        ]
        if stock_code:
            blocks.append(fallback_quote_block(stock_code))
        text = "\n\n".join(blocks)
        save_user_context(
            {
                "last_scene": kind,
                "last_stock": stock_code,
                "default_horizon": horizon,
                "last_trade_date": status["latest_trade_date"],
                "updated_at": status["latest_trade_date"],
            }
        )
        return text

    blocks = [tushare_block(status)]
    if kind == "candidates":
        blocks.append(candidates_answer(question, market, status, tips))
    elif kind == "holding":
        blocks.append(holding_answer(question, holdings, market, tips))
    elif kind == "sector":
        blocks.append(sector_answer(question, market))
    else:
        blocks.append(generic_answer(question, cash, market, tips))
    save_user_context(
        {
            "last_scene": kind,
            "last_stock": stock_code,
            "default_horizon": horizon,
            "last_trade_date": status["latest_trade_date"],
            "updated_at": status["latest_trade_date"],
        }
    )
    return "\n\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local conversation entry for stock model")
    parser.add_argument("--question", default="")
    parser.add_argument("--cash", type=float, default=None)
    parser.add_argument("--holdings", default="")
    args = parser.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = answer(args.question, cash=args.cash, holdings=args.holdings)
    out = OUT_DIR / "latest_answer.md"
    out.write_text(text, encoding="utf-8")
    print(json.dumps({"output": str(out)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
