from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_powershell(command: str) -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
    )
    return completed.stdout.strip()


def top_files(limit: int = 15) -> list[dict]:
    ignored_parts = {".git", ".venv", "__pycache__"}
    rows: list[dict] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in ignored_parts for part in rel.parts):
            continue
        rows.append({"path": str(rel), "mb": round(path.stat().st_size / 1024 / 1024, 2)})
    return sorted(rows, key=lambda item: item["mb"], reverse=True)[:limit]


def main() -> None:
    codexignore = ROOT / ".codexignore"
    report = {
        "workspace": str(ROOT),
        "codexignore_exists": codexignore.exists(),
        "proxy_env": {
            "HTTP_PROXY": os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy"),
            "HTTPS_PROXY": os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"),
        },
        "project_codex_env_exists": (ROOT / ".codex" / ".env").exists(),
        "python_processes": run_powershell(
            "Get-Process python,python3,py -ErrorAction SilentlyContinue | "
            "Select-Object Id,ProcessName,CPU,StartTime,Path | ConvertTo-Json -Depth 3"
        ),
        "top_cpu_processes": run_powershell(
            "Get-Process | Sort-Object CPU -Descending | Select-Object -First 12 "
            "Id,ProcessName,CPU,StartTime,Path | ConvertTo-Json -Depth 3"
        ),
        "largest_workspace_files_mb": top_files(),
        "recommendations": [
            "如果存在长时间高CPU的python进程，优先确认是否为残留测试任务。",
            "保持.codexignore，避免数据库、虚拟环境、历史报告和媒体文件进入Codex上下文。",
            "长任务优先拆分为单路径/小批次，并给脚本增加查询缓存和超时。",
            "连接慢时检查代理端口是否仍可用，再检查OpenAI状态页是否有Codex延迟事件。",
        ],
    }
    outdir = ROOT / "reports" / "diagnostics"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / "codex_performance_diagnostics.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "report": str(out)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
