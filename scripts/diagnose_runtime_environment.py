from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scoring_system.env_loader import load_project_env
from scoring_system.env_loader import local_proxy_available

load_project_env()
REPORT_DIR = ROOT / "reports" / "diagnostics"
DB_2025 = Path(r"D:\股票AI交易助手数据\sqlite\market_2025.sqlite")


def status(name: str, state: str, detail: str = "") -> dict:
    return {"name": name, "status": state, "detail": detail}


def run_cmd(cmd: list[str], timeout: int = 10) -> dict:
    started = time.perf_counter()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
        elapsed = round(time.perf_counter() - started, 3)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "elapsed_sec": elapsed,
            "stdout": proc.stdout.strip()[-1000:],
            "stderr": proc.stderr.strip()[-1000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": None, "elapsed_sec": timeout, "stdout": "", "stderr": "TIMEOUT"}


def check_python() -> dict:
    return status("python", "OK", sys.version.replace("\n", " "))


def check_workspace_write() -> dict:
    target = REPORT_DIR / "runtime_write_test.tmp"
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        target.write_text("ok", encoding="utf-8")
        text = target.read_text(encoding="utf-8")
        target.unlink(missing_ok=True)
        return status("workspace_write", "OK" if text == "ok" else "WARN", str(target))
    except Exception as exc:
        return status("workspace_write", "FAIL", f"{type(exc).__name__}: {exc}")


def check_d_drive_file() -> dict:
    try:
        if not DB_2025.exists():
            return status("d_drive_database_file", "WARN", f"not found: {DB_2025}")
        size = DB_2025.stat().st_size
        with DB_2025.open("rb") as fh:
            fh.read(16)
        return status("d_drive_database_file", "OK", f"{DB_2025} size={size}")
    except Exception as exc:
        return status("d_drive_database_file", "FAIL", f"{type(exc).__name__}: {exc}")


def check_sqlite_open_modes() -> list[dict]:
    checks: list[dict] = []
    if not DB_2025.exists():
        return [status("sqlite_2025_open", "WARN", "database missing")]
    try:
        conn = sqlite3.connect(str(DB_2025))
        count = conn.execute("select count(*) from trade_cal").fetchone()[0]
        conn.close()
        checks.append(status("sqlite_normal_open", "OK", f"trade_cal={count}"))
    except Exception as exc:
        checks.append(status("sqlite_normal_open", "WARN", f"{type(exc).__name__}: {exc}; use read-only URI fallback"))
    try:
        uri = f"file:{quote(str(DB_2025))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        count = conn.execute("select count(*) from trade_cal").fetchone()[0]
        conn.close()
        checks.append(status("sqlite_readonly_uri_open", "OK", f"trade_cal={count}"))
    except Exception as exc:
        checks.append(status("sqlite_readonly_uri_open", "FAIL", f"{type(exc).__name__}: {exc}"))
    return checks


def check_proxy_env() -> dict:
    keys = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]
    found = {key: os.environ.get(key) for key in keys if os.environ.get(key)}
    project_env = ROOT / ".codex" / ".env"
    project_proxy = ""
    if project_env.exists():
        text = project_env.read_text(encoding="utf-8", errors="ignore")
        project_proxy = "; ".join(line for line in text.splitlines() if "PROXY" in line.upper())
    if found:
        return status("proxy_env", "OK", json.dumps(found, ensure_ascii=False))
    if project_proxy:
        stale = []
        for line in project_proxy.split("; "):
            if "=" not in line:
                continue
            _key, value = line.split("=", 1)
            if not local_proxy_available(value):
                stale.append(value)
        if stale:
            return status("proxy_env", "OK", f"stale local proxy skipped: {', '.join(stale)}")
        return status("proxy_env", "WARN", f"process env empty, project .codex/.env has {project_proxy}")
    return status("proxy_env", "WARN", "no proxy env found")


def check_powershell_latency() -> dict:
    result = run_cmd(["powershell", "-NoProfile", "-Command", "Get-Date"], timeout=8)
    state = "OK" if result["ok"] and result["elapsed_sec"] < 3 else "WARN"
    return status("powershell_latency", state, json.dumps(result, ensure_ascii=False))


def check_core_scripts_compile() -> dict:
    scripts = [
        "scripts/health_check.py",
        "scripts/run_walk_forward_2025_mvp.py",
        "scripts/build_2025_test_cases.py",
        "scripts/fill_2025_test_cases.py",
    ]
    cmd = [sys.executable, "-m", "py_compile", *scripts]
    result = run_cmd(cmd, timeout=20)
    return status("core_scripts_compile", "OK" if result["ok"] else "FAIL", json.dumps(result, ensure_ascii=False))


def recommendations(checks: list[dict]) -> list[str]:
    recs = [
        "D盘SQLite读取优先使用只读URI，避免沙箱或锁文件导致普通connect失败。",
        "耗时任务先只跑单条路径或小样本，确认流程后再扩展，避免长时间思考和超时。",
        "飞书通知只在本地文件和验证全部完成后发送。",
        "正式作答只读取questions文件，validation_private只在决策完成后给评分器使用。",
    ]
    if any(c["name"] == "proxy_env" and c["status"] != "OK" for c in checks):
        recs.append("当前进程代理环境可能未继承项目.codex/.env；网络卡顿时优先检查Codex进程是否加载代理。")
    if any(c["name"] == "sqlite_normal_open" and c["status"] != "OK" for c in checks):
        recs.append("普通SQLite连接不稳定时，不要反复重试，直接切换只读URI模式。")
    return recs


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict] = [
        check_python(),
        check_workspace_write(),
        check_d_drive_file(),
        check_proxy_env(),
        check_powershell_latency(),
        check_core_scripts_compile(),
    ]
    checks.extend(check_sqlite_open_modes())
    data = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": str(ROOT),
        "checks": checks,
        "recommendations": recommendations(checks),
    }
    json_path = REPORT_DIR / "runtime_environment_diagnostics.json"
    md_path = REPORT_DIR / "runtime_environment_diagnostics.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 运行环境诊断报告", "", f"- 生成时间：{data['generated_at']}", f"- 项目目录：`{ROOT}`", ""]
    lines.extend(["| 检查项 | 状态 | 说明 |", "| -- | -- | -- |"])
    for item in checks:
        lines.append(f"| {item['name']} | {item['status']} | {item['detail']} |")
    lines.extend(["", "## 建议", ""])
    for rec in data["recommendations"]:
        lines.append(f"- {rec}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "checks": checks}, ensure_ascii=False, indent=2))
    return 2 if any(c["status"] == "FAIL" for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
