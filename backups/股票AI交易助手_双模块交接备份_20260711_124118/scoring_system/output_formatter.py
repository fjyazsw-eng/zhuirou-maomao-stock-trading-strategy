from __future__ import annotations

from typing import Any


def compact_table(title: str, rows: list[tuple[str, str]]) -> str:
    lines = [title, "", "项目| 结论", "|---|---|"]
    lines.extend(f"{key}| {value}" for key, value in rows)
    return "\n".join(lines)


def compact_trade_advice(
    empty_action: str,
    holding_action: str,
    add_action: str,
    sell_action: str,
    buy_condition: str,
    reduce_condition: str,
    stop_condition: str,
    max_position: str,
    final_line: str,
) -> str:
    lines = [
        "直接建议",
        "",
        "用户状态| 操作",
        "|---|---|",
        f"空仓| {empty_action}",
        f"已持仓| {holding_action}",
        f"准备加仓| {add_action}",
        f"准备卖出| {sell_action}",
        "",
        "执行条件",
        "",
        f"- 买入条件：{buy_condition}",
        f"- 减仓条件：{reduce_condition}",
        f"- 止损条件：{stop_condition}",
        f"- 仓位上限：{max_position}",
        "",
        "最终一句话",
        "",
        final_line,
    ]
    return "\n".join(lines)


def one_line_reason(text: str, limit: int = 50) -> str:
    text = (text or "").strip().replace("\n", " ")
    return text[:limit]


def limit_lines(lines: list[str], max_lines: int) -> list[str]:
    return [line for line in lines if line.strip()][:max_lines]


def safe_value(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback
