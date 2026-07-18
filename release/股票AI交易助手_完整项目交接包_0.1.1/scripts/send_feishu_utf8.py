from __future__ import annotations

import argparse
import base64
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.push_gateway import send


def main() -> int:
    parser = argparse.ArgumentParser(description="Send Feishu message with UTF-8 safe inputs")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--text-file", help="UTF-8 text file path")
    group.add_argument("--text-b64", help="Base64-encoded UTF-8 text")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")
    else:
        text = base64.b64decode(args.text_b64.encode("ascii")).decode("utf-8")

    result = send("feishu", text, dry_run=args.dry_run)
    print(result)
    return 0 if result.get("sent") or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
