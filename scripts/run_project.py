from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.portable_setup_check import evaluate_setup
from scoring_system.workflow_orchestrator import main as workflow_main


SAFE_COMMANDS = {"setup", "status", "validate", "show-help"}
WORKFLOW_ROUTES = {
    "status": ["status"],
    "next": ["next"],
    "validate": ["validate"],
    "weekend-start": ["weekend"],
    "night-plan": ["night-plan"],
    "intraday-check": ["intraday-check"],
    "closing-review": ["closing-review"],
    "weekly-review": ["weekly-review"],
}


def run_workflow_command(args: list[str]) -> int:
    return workflow_main(args)


def _workflow_exit_code(args: list[str]) -> int:
    result = run_workflow_command(args)
    return result if isinstance(result, int) else 0


def _print_help() -> None:
    print(
        "\n".join(
            [
                "股票AI交易助手统一入口",
                "setup: 运行环境检查",
                "status: 只读查看当前阶段",
                "next: 运行工作流下一步建议",
                "validate: 校验状态和编排器",
                "weekend-start/night-plan/intraday-check/closing-review/weekly-review: 路由到底层工作流",
            ]
        )
    )


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default="show-help")
    parser.add_argument("remaining", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command

    if command == "show-help":
        _print_help()
        return 0
    if command not in SAFE_COMMANDS and command not in WORKFLOW_ROUTES:
        print(json.dumps({"status": "NOT_READY", "error": f"unknown command: {command}"}, ensure_ascii=False, indent=2))
        return 2
    if command == "setup":
        setup = evaluate_setup(root=root)
        print(json.dumps(setup, ensure_ascii=False, indent=2))
        return 0 if setup["status"] in {"READY", "READY_WITH_WARNINGS"} else 2
    if command in {"status", "validate"}:
        return _workflow_exit_code(WORKFLOW_ROUTES[command] + args.remaining)

    setup = evaluate_setup(root=root, skip_network=True)
    if setup["status"] == "NOT_READY":
        print(json.dumps({"status": "NOT_READY", "blocked_command": command, "setup": setup}, ensure_ascii=False, indent=2))
        return 2
    route = WORKFLOW_ROUTES[command]
    return _workflow_exit_code(route + args.remaining)


if __name__ == "__main__":
    raise SystemExit(main())
