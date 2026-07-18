from __future__ import annotations

import importlib
import json
import os
import socket
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

DEFAULT_MODULES = [
    "pandas",
    "numpy",
    "yaml",
    "requests",
    "tushare",
    "scoring_system.workflow_state",
    "scoring_system.systemic_risk_gate",
    "scoring_system.hexagram_calibration",
    "scoring_system.workflow_orchestrator",
]

SENSITIVE_TOKEN_KEYS = ("TUSHARE_REPLAY_API_KEY", "TUSHARE_TOKEN", "TUSHARE_TOKEN_PRO")


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}***{value[-3:]}"


def _load_env_file(root: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    path = root / ".env"
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _add(target: list[str], value: str) -> None:
    if value not in target:
        target.append(value)


def _check_workflow_state(path: Path) -> tuple[bool, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        required = [
            "workflow_version",
            "current_stage",
            "weekend_reality_analysis",
            "hexagram_manual_input",
            "weekly_strategy",
            "night_plan",
            "intraday_veto_result",
            "daily_execution_state",
        ]
        missing = [key for key in required if key not in payload]
        if missing:
            return False, f"workflow state invalid: missing {','.join(missing)}"
        return True, "workflow_state_valid"
    except Exception as exc:
        return False, f"workflow state invalid: {type(exc).__name__}"


def _tcp_connect(host: str, port: int, timeout_seconds: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def evaluate_setup(
    *,
    root: Path = ROOT,
    env: dict[str, str] | None = None,
    skip_network: bool = False,
    module_names: list[str] | None = None,
    network_timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    root = Path(root)
    merged_env = dict(os.environ) if env is None else {}
    merged_env.update(_load_env_file(root))
    if env is not None:
        merged_env.update(env)

    passed: list[str] = []
    warnings: list[str] = []
    failed: list[str] = []
    actions: list[str] = []

    if sys.version_info.major == 3 and 11 <= sys.version_info.minor < 14:
        _add(passed, f"python:{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    else:
        _add(failed, "python version must be >=3.11,<3.14")
        _add(actions, "Install Python 3.11, 3.12, or 3.13.")

    if root.exists():
        _add(passed, "project_path_exists")
    else:
        _add(failed, "project path missing")

    for rel in [
        "requirements.txt",
        "requirements-dev.txt",
        ".env.example",
        "skills/stock-ai-workflow-controller/SKILL.md",
        "reports/workflow/current_workflow_state.json",
        "config/project_config.example.yaml",
        "tests",
    ]:
        if (root / rel).exists():
            _add(passed, f"file_exists:{rel}")
        else:
            _add(failed, f"required file missing:{rel}")
            _add(actions, f"Restore {rel} from the repository.")

    for module in module_names if module_names is not None else DEFAULT_MODULES:
        try:
            importlib.import_module(module)
            _add(passed, f"import:{module}")
        except Exception as exc:
            _add(failed, f"import failed:{module}:{type(exc).__name__}")
            _add(actions, "Install requirements and ensure commands run from the project root.")

    token_key = next((key for key in SENSITIVE_TOKEN_KEYS if merged_env.get(key)), "")
    if token_key:
        _add(passed, f"token_present:{token_key}={mask_secret(str(merged_env[token_key]))}")
    else:
        _add(failed, "Tushare token missing")
        _add(actions, "Copy .env.example to .env and set TUSHARE_REPLAY_API_KEY or TUSHARE_TOKEN.")

    state_path = root / "reports" / "workflow" / "current_workflow_state.json"
    if state_path.exists():
        ok, message = _check_workflow_state(state_path)
        _add(passed if ok else failed, message)
        if not ok:
            _add(actions, "Recreate workflow state from reports/workflow/current_workflow_state.example.json.")

    report_dir = root / "reports"
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        probe = report_dir / ".setup_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        _add(passed, "reports_writable")
    except Exception as exc:
        _add(failed, f"reports not writable:{type(exc).__name__}")

    if skip_network:
        _add(passed, "network_checks_skipped")
    else:
        if _tcp_connect("push2.eastmoney.com", 443, network_timeout_seconds):
            _add(passed, "eastmoney_connectable")
        else:
            _add(warnings, "eastmoney connectivity check failed")
        if token_key and _tcp_connect("ts.gyzcloud.top", 443, network_timeout_seconds):
            _add(passed, "tushare_endpoint_connectable")
        elif token_key:
            _add(warnings, "tushare endpoint connectivity check failed")

    if failed:
        status = "NOT_READY"
    elif warnings:
        status = "READY_WITH_WARNINGS"
    else:
        status = "READY"
    return {
        "status": status,
        "project_root": str(root),
        "passed_checks": passed,
        "warnings": warnings,
        "failed_checks": failed,
        "recommended_actions": actions,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Portable setup check for the stock AI workflow.")
    parser.add_argument("--skip-network", action="store_true", help="Skip Eastmoney and Tushare connectivity probes.")
    args = parser.parse_args(argv)
    result = evaluate_setup(skip_network=args.skip_network)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"READY", "READY_WITH_WARNINGS"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
