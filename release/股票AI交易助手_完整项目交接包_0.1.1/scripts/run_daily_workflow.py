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


def run_step(name: str, args: list[str], *, required_inputs: list[Path] | None = None) -> dict[str, object]:
    missing = [str(path) for path in (required_inputs or []) if not path.exists()]
    if missing:
        return {"name": name, "status": "SKIPPED", "returncode": None, "input": missing, "output": "", "error": "", "skipped_reason": "missing prerequisites"}
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
    status = "PASS" if proc.returncode == 0 else "FAIL"
    safe_print(f"[{status}] {name} returncode={proc.returncode}")
    return {
        "name": name,
        "status": status,
        "returncode": proc.returncode,
        "input": " ".join(args),
        "output": proc.stdout[-2000:],
        "error": proc.stderr[-2000:],
        "skipped_reason": "",
    }


def newest(pattern: str) -> str:
    files = sorted(REPORTS.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(files[0]) if files else ""


def main() -> int:
    safe_print(f"Working directory: {ROOT}")
    steps: list[dict[str, object]] = []
    steps.append(run_step("健康检查", ["scripts/health_check.py"]))
    steps.append(run_step("Tushare实时探针", ["scripts/tushare_realtime_probe.py"]))
    score_dir = ROOT / "data" / "processed" / "scores"
    decision_dir = ROOT / "data" / "processed" / "decisions"
    score_inputs = list(score_dir.glob("*")) if score_dir.exists() else []
    decision_inputs = list(decision_dir.glob("*")) if decision_dir.exists() else []
    steps.append(run_step("刷新市场总览和HTML看板", ["scoring_system/hierarchy_report.py"], required_inputs=score_inputs[:1] if score_inputs else [score_dir / "<score-artifact>"]))
    steps.append(run_step("生成空仓/持仓和账户级建议", ["scoring_system/position_advisor.py", "--cash", "50000"], required_inputs=decision_inputs[:1] if decision_inputs else [decision_dir / "<decision-artifact>"]))
    steps.append(run_step("检查日常输出", ["scripts/check_daily_outputs.py"]))

    outputs = {
        "latest_market_report": str(REPORTS / "latest_market_decision_report.md") if (REPORTS / "latest_market_decision_report.md").exists() else "",
        "latest_dashboard": str(REPORTS / "latest_market_decision_dashboard.html") if (REPORTS / "latest_market_decision_dashboard.html").exists() else "",
        "position_advice": newest("advice/position_advice_*.md"),
        "account_position_advice": newest("advice/account_position_advice_*.md"),
    }
    core_outputs = outputs["latest_market_report"] and outputs["latest_dashboard"]
    failed = any(x["status"] == "FAIL" for x in steps)
    skipped = any(x["status"] == "SKIPPED" for x in steps)
    overall = "PASS" if core_outputs and not failed and not skipped else ("BLOCKED" if failed else "PARTIAL")
    summary = {
        "steps": steps,
        "outputs": outputs,
        "status": overall,
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
        lines.append(f"- {step['name']}: status={step['status']}, returncode={step['returncode']}, skipped_reason={step['skipped_reason'] or '无'}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    safe_print("\n== 日常流程摘要 ==")
    safe_print(json.dumps({"status": summary["status"], "markdown": str(md_path), "json": str(json_path), "outputs": outputs}, ensure_ascii=False, indent=2))
    return 0 if overall == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
