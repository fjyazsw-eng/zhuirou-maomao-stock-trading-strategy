from __future__ import annotations

import importlib
import json
import os
import re
import socket
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from scoring_system.env_loader import load_project_env
from scoring_system.project_paths import data_dir, database_path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""


def _dependency(name: str, module: str) -> Check:
    try:
        importlib.import_module(module)
        return Check(name, "PASS", "已安装")
    except Exception as exc:
        return Check(name, "FAIL", f"{type(exc).__name__}", f"运行 pip install -r requirements.txt")


def _json_check(path: Path, required: bool) -> Check:
    if not path.exists():
        status = "FAIL" if required else "WARN"
        return Check(str(path.relative_to(ROOT)), status, "文件不存在", "从对应 .example.json 复制后再填写")
    try:
        json.loads(path.read_text(encoding="utf-8"))
        return Check(str(path.relative_to(ROOT)), "PASS", "JSON有效")
    except Exception as exc:
        return Check(str(path.relative_to(ROOT)), "FAIL", f"JSON无效：{type(exc).__name__}", "修复JSON语法")


def _network_check() -> Check:
    try:
        with socket.create_connection(("push2delay.eastmoney.com", 443), timeout=3):
            return Check("network", "PASS", "东方财富主机可连接")
    except OSError as exc:
        return Check("network", "WARN", f"暂不可连接：{type(exc).__name__}", "检查网络、DNS或代理；离线演示仍可用")


def _hardcoded_paths() -> Check:
    pattern = re.compile(r"[A-Za-z]:[\\/](?![\\/]|Software[\\/])")
    hits: list[str] = []
    for folder in (ROOT / "scoring_system", ROOT / "scripts", ROOT / "config"):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".py", ".ps1", ".json", ".yaml", ".yml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(text):
                hits.append(str(path.relative_to(ROOT)))
    if hits:
        return Check("portable_paths", "FAIL", ", ".join(hits[:8]), "改用 STOCK_AI_DATA_DIR / STOCK_AI_DATABASE_PATH 或相对路径")
    return Check("portable_paths", "PASS", "未发现个人磁盘绝对路径")


def _trading_session(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.strftime("%H:%M")
    return "09:25" <= current <= "11:35" or "12:55" <= current <= "15:05"


def run_health(root: Path = ROOT, now: datetime | None = None) -> dict[str, object]:
    load_project_env()
    current = now or datetime.now()
    checks: list[Check] = []
    supported = sys.version_info[:2] in {(3, 11), (3, 12)}
    checks.append(Check("python", "PASS" if supported else "FAIL", sys.version.split()[0], "安装64位 Python 3.11或3.12" if not supported else ""))
    for name, module in [("pandas", "pandas"), ("numpy", "numpy"), ("PyYAML", "yaml"), ("tushare", "tushare"), ("requests", "requests"), ("urllib3", "urllib3")]:
        checks.append(_dependency(name, module))
    env_path = root / ".env"
    checks.append(Check(".env", "PASS" if env_path.exists() else "WARN", "存在" if env_path.exists() else "未创建", "复制 .env.example 为 .env" if not env_path.exists() else ""))
    token_present = bool(os.environ.get("TUSHARE_REPLAY_API_KEY") or os.environ.get("TUSHARE_TOKEN") or os.environ.get("TUSHARE_TOKEN_PRO"))
    checks.append(Check("tushare_token", "PASS" if token_present else "WARN", "已配置（不显示内容）" if token_present else "未配置", "演示模式可用；实时历史分析需配置Token" if not token_present else ""))
    checks.append(_json_check(root / "config" / "realtime_watchlist.example.json", True))
    checks.append(_json_check(root / "config" / "realtime_watchlist.json", False))
    target_dir = data_dir(root)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe = target_dir / ".write_test"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        checks.append(Check("data_dir", "PASS", f"可写：{target_dir}"))
    except OSError as exc:
        checks.append(Check("data_dir", "FAIL", f"不可写：{type(exc).__name__}", "修改数据目录权限或 STOCK_AI_DATA_DIR"))
    db = database_path(root)
    checks.append(Check("database", "PASS" if db.exists() else "WARN", str(db), "无数据库时使用demo；正式分析前放置或生成数据库" if not db.exists() else ""))
    checks.append(_network_check())
    push_ready = bool(os.environ.get("FEISHU_WEBHOOK") or os.environ.get("WECOM_WEBHOOK") or os.environ.get("TELEGRAM_BOT_TOKEN"))
    checks.append(Check("push_channel", "PASS" if push_ready else "WARN", "已配置" if push_ready else "未配置", "本地分析不受影响；需要通知时再配置" if not push_ready else ""))
    checks.append(Check("trading_session", "PASS", "是" if _trading_session(current) else "否"))
    for module in ("scoring_system.tushare_client", "scoring_system.realtime_watch_monitor", "scoring_system.execution_decision_engine"):
        checks.append(_dependency(f"import:{module}", module))
    checks.append(_hardcoded_paths())
    if any(item.status == "FAIL" for item in checks):
        status = "FAIL"
    elif any(item.status == "WARN" for item in checks):
        status = "PASS_WITH_WARNINGS"
    else:
        status = "PASS"
    return {"status": status, "generated_at": current.isoformat(timespec="seconds"), "checks": [asdict(item) for item in checks]}


def print_health(report: dict[str, object]) -> None:
    print(f"Health status: {report['status']}")
    for item in report["checks"]:  # type: ignore[index]
        fix = f" | 修复：{item['fix']}" if item.get("fix") else ""
        print(f"[{item['status']}] {item['name']}: {item['detail']}{fix}")
