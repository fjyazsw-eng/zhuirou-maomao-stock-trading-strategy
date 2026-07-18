from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.tushare_freshness_agent import LATEST_FRESHNESS_JSON, run_freshness_probe


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify latest complete Tushare rows for formal stock AI recommendations.")
    parser.add_argument("--today", default=None, help="Natural date in YYYYMMDD; defaults to current date.")
    parser.add_argument("--output", default=str(LATEST_FRESHNESS_JSON), help="Output JSON path.")
    args = parser.parse_args()

    result = run_freshness_probe(today=args.today, output_path=Path(args.output))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
