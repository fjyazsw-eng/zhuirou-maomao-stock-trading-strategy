from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.env_loader import load_project_env
from scoring_system.network_env import clear_bad_tushare_proxy
from scoring_system.tushare_client import get_tushare_pro
from scoring_system.verified_market_snapshot import FAST_CONTEXT_DIR, build_verified_market_snapshot, write_verified_market_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a freshness-gated verified market snapshot.")
    parser.add_argument("--today", default=None, help="Natural date in YYYYMMDD; defaults to current date.")
    parser.add_argument("--output-dir", default=str(FAST_CONTEXT_DIR), help="Directory for dated and latest snapshot JSON.")
    args = parser.parse_args()

    load_project_env(override=True)
    clear_bad_tushare_proxy()
    pro = get_tushare_pro()
    snapshot = build_verified_market_snapshot(pro=pro, today=args.today)
    paths = write_verified_market_snapshot(snapshot, output_dir=Path(args.output_dir))
    print(
        json.dumps(
            {
                "snapshot_status": snapshot.get("snapshot_status"),
                "trade_date": snapshot.get("trade_date"),
                "formal_recommendation_allowed": snapshot.get("formal_recommendation_allowed"),
                "market_state": (snapshot.get("market") or {}).get("state"),
                "dated": str(paths["dated"]),
                "latest": str(paths["latest"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if snapshot.get("snapshot_status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
