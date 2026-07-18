from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from scoring_system.portable_analysis import analyze_request, load_input
from scoring_system.portable_health import print_health, run_health


def run(command: list[str]) -> int:
    return subprocess.run(command, cwd=ROOT).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="股票AI交易助手统一入口")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health-check", help="检查安装、数据、网络和可选消息渠道")
    analyze = sub.add_parser("analyze", help="校验结构化分析输入并安全调度")
    analyze.add_argument("--input", type=Path, required=True)
    sub.add_parser("daily-report", help="调用现有日报/层级报告模块")
    sub.add_parser("watch-once", help="运行一次只读盯盘，不发送消息")
    sub.add_parser("watch-start", help="持续运行只读盯盘；消息渠道需另行配置")
    sub.add_parser("test", help="运行最小自动测试")
    sub.add_parser("demo", help="显示离线演示数据和完整输出结构")
    args = parser.parse_args()

    if args.command == "health-check":
        report = run_health(ROOT)
        print_health(report)
        return 2 if report["status"] == "FAIL" else 0
    if args.command == "analyze":
        print(json.dumps(analyze_request(load_input(args.input)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "daily-report":
        return run([sys.executable, "-m", "scoring_system.hierarchy_report"])
    if args.command == "watch-once":
        return run([sys.executable, "scripts/run_realtime_watch_monitor.py", "--once"])
    if args.command == "watch-start":
        return run([sys.executable, "scripts/run_realtime_watch_monitor.py", "--send"])
    if args.command == "test":
        return run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
    if args.command == "demo":
        payload = json.loads((ROOT / "sample_data" / "demo_snapshot.json").read_text(encoding="utf-8"))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
