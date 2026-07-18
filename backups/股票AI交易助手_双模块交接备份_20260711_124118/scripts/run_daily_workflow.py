from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
REPORTS = ROOT / "reports"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def safe_print(text: object = "") -> None:
    print(str(text).encode("utf-8", errors="replace").decode("utf-8", errors="replace"))


def run_step(name: str, args: list[str]) -> dict[str, object]:
    safe_print(f"\n== {name} ==")
    proc = subprocess.run(
        [PYTHON, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.stdout.strip():
        safe_print(proc.stdout.strip())
    if proc.stderr.strip():
        safe_print(proc.stderr.strip())
    status = "OK" if proc.returncode == 0 else "WARN"
    safe_print(f"[{status}] {name} returncode={proc.returncode}")
    return {
        "name": name,
        "command": " ".join([PYTHON, *args]),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def newest(pattern: str) -> str:
    files = sorted(REPORTS.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else ""


def main() -> int:
    safe_print(f"Working directory: {ROOT}")
    steps: list[dict[str, object]] = []
    steps.append(run_step("健康检查", ["scripts/health_check.py"]))
    steps.append(run_step("Tushare实时探针", ["scripts/tushare_realtime_probe.py"]))
    steps.append(run_step("刷新市场总览和HTML看板", ["scoring_system/hierarchy_report.py"]))
    steps.append(run_step("生成空仓/持仓和账户级建议", ["scoring_system/position_advisor.py", "--cash", "50000"]))
    steps.append(run_step("检查日常输出", ["scripts/check_daily_outputs.py"]))

    outputs = {
        "latest_market_report": str(REPORTS / "latest_market_decision_report.md"),
        "latest_dashboard": str(REPORTS / "latest_market_decision_dashboard.html"),
        "position_advice": newest("advice/position_advice_*.md"),
        "account_position_advice": newest("advice/account_position_advice_*.md"),
    }
    summary = {
        "steps": steps,
        "outputs": outputs,
        "status": "PASS" if all(int(x["returncode"]) == 0 for x in steps) else "PASS_WITH_WARNINGS",
    }
    out_dir = REPORTS / "workflow"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "daily_workflow_latest.json"
    md_path = out_dir / "daily_workflow_latest.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 日常运行流程结果",
        "",
        f"- 状态：{summary['status']}",
        f"- 工作目录：{ROOT}",
        "",
        "## 输出文件",
    ]
    for key, value in outputs.items():
        lines.append(f"- {key}: {value or '未找到'}")
    lines += ["", "## 步骤结果"]
    for step in steps:
        lines.append(f"- {step['name']}: returncode={step['returncode']}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    safe_print("\n== 日常流程摘要 ==")
    safe_print(json.dumps({"status": summary["status"], "markdown": str(md_path), "json": str(json_path), "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
