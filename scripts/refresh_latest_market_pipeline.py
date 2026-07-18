from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def run_step(name: str, args: list[str]) -> dict[str, object]:
    proc = subprocess.run(
        [PYTHON, *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "name": name,
        "command": " ".join([PYTHON, *args]),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-1500:],
        "stderr_tail": proc.stderr[-1500:],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh latest market pipeline to target trade date")
    parser.add_argument("--target-date", required=True)
    parser.add_argument("--cash", type=float, default=50000.0)
    args = parser.parse_args()

    target = args.target_date
    planned_steps = [
        ("online_update", ["-m", "scoring_system.mvp_update", "--online", "--end-date", target]),
        ("market_score", ["-m", "scoring_system.mvp_score", "--as-of", target]),
        ("leader_score", ["-m", "scoring_system.leader_score", "--as-of", target]),
        ("stock_score", ["-m", "scoring_system.stock_score", "--as-of", target]),
        ("decision_engine", ["-m", "scoring_system.decision_engine", "--as-of", target]),
        ("sector_alerts", ["-m", "scoring_system.sector_alerts"]),
        ("position_advisor", ["-m", "scoring_system.position_advisor", "--cash", str(args.cash)]),
        ("hierarchy_report", ["-m", "scoring_system.hierarchy_report", "--as-of", target]),
    ]
    steps: list[dict[str, object]] = []
    failed = False
    for name, command in planned_steps:
        if failed:
            steps.append(
                {
                    "name": name,
                    "command": " ".join([PYTHON, *command]),
                    "returncode": None,
                    "stdout_tail": "",
                    "stderr_tail": "",
                    "skipped": "previous_step_failed",
                }
            )
            continue
        step = run_step(name, command)
        steps.append(step)
        failed = int(step["returncode"]) != 0

    payload = {
        "target_date": target,
        "status": "PASS" if all(int(step["returncode"]) == 0 for step in steps) else "WARN",
        "steps": steps,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
