from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import html


STATUS_LABELS = {
    "online_update": "是否在线更新成功",
    "online_error": "在线更新错误",
    "run_date": "运行日期",
    "data_trade_date": "数据最新交易日",
    "market_score": "市场评分",
    "ready_core_count": "READY_CORE数量",
    "ready_secondary_count": "READY_SECONDARY数量",
    "wait_pullback_core_count": "WAIT_PULLBACK_CORE数量",
    "weak_structure_count": "WEAK_STRUCTURE数量",
    "avoid_count": "AVOID数量",
    "missing_data": "数据缺失",
    "manual_check": "是否需要人工检查",
}


def status_value(lines: list[str], label: str) -> str:
    prefix = f"- {label}："
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix):].strip()
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", required=True)
    parser.add_argument("--temp-output", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--exit-code", required=True)
    args = parser.parse_args()

    status_path = Path(args.status)
    temp_output_path = Path(args.temp_output)
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    lines_out = [
        f"run_time={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"script_exit_code={args.exit_code}",
    ]

    html_path = status_path.with_suffix(".html")
    if status_path.exists():
        status_lines = status_path.read_text(encoding="utf-8").splitlines()
        html_path.write_text(render_status_html(status_lines), encoding="utf-8")
        for key, label in STATUS_LABELS.items():
            value = status_value(status_lines, label)
            if value:
                lines_out.append(f"{key}={value}")
        lines_out.append(f"status_report={status_path}")
        lines_out.append(f"html_report={html_path}")
    else:
        lines_out.append("error=latest_run_status.md not generated")

    if args.exit_code != "0":
        lines_out.append("error_summary=simulation command failed")
        if temp_output_path.exists():
            tail = temp_output_path.read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
            lines_out.extend(f"stderr_tail={line}" for line in tail)
    elif temp_output_path.exists():
        temp_lines = temp_output_path.read_text(encoding="utf-8", errors="replace").splitlines()
        warning = next((line for line in temp_lines if line.startswith("WARN online update failed")), "")
        lines_out.append(f"error_summary={warning or 'none'}")
    else:
        lines_out.append("error_summary=none")

    log_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    return 0


def render_status_html(lines: list[str]) -> str:
    title = "股票策略研究室 - 每日模拟状态"
    body_lines = []
    for line in lines:
        if line.startswith("# "):
            body_lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("- "):
            text = html.escape(line[2:])
            if "：" in text:
                label, value = text.split("：", 1)
                body_lines.append(f"<li><strong>{label}</strong>：{value}</li>")
            else:
                body_lines.append(f"<li>{text}</li>")
        elif line.strip():
            body_lines.append(f"<p>{html.escape(line)}</p>")
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <style>
    body {{ font-family: "Microsoft YaHei", Arial, sans-serif; margin: 32px; color: #1f2937; background: #f8fafc; }}
    main {{ max-width: 880px; margin: auto; background: white; border: 1px solid #e5e7eb; padding: 28px 32px; }}
    h1 {{ font-size: 24px; margin-top: 0; }}
    li {{ list-style: none; padding: 8px 0; border-bottom: 1px solid #eef2f7; }}
    strong {{ display: inline-block; min-width: 190px; color: #111827; }}
  </style>
</head>
<body><main>{body}</main></body>
</html>
""".format(title=html.escape(title), body="\n".join(body_lines))


if __name__ == "__main__":
    raise SystemExit(main())
