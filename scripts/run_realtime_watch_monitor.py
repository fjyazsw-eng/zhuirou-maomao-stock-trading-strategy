from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.realtime_watch_monitor import DEFAULT_CONFIG, RealtimeWatchMonitor, is_trading_session, load_config


def main() -> int:
    parser = argparse.ArgumentParser(description="股票AI交易助手只读实时盯盘")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--once", action="store_true", help="只运行一轮")
    parser.add_argument("--send", action="store_true", help="通过 CC Connect 推送状态变化")
    parser.add_argument("--force-notify", action="store_true", help="忽略去重，强制推送当前可通知状态")
    parser.add_argument("--session-only", action="store_true", help="只在交易时段运行，非交易时段直接退出")
    args = parser.parse_args()
    monitor = RealtimeWatchMonitor(load_config(args.config), config_path=args.config)
    if args.once:
        if args.session_only and not is_trading_session(__import__("datetime").datetime.now()):
            print(json.dumps({"ok": True, "skipped": True, "reason": "outside_trading_session"}, ensure_ascii=False, indent=2))
            return 0
        report = monitor.run_once(send=args.send, force_notify=args.force_notify)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(item["state"] != "DATA_ERROR" for item in report["decisions"]) else 2
    monitor.run_forever(send=args.send, session_only=args.session_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
