from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scoring_system.conversation_entry import answer
from scoring_system.push_gateway import send, build_question_message


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="生成引导式问答，可选推送到飞书")
    parser.add_argument("--question", required=True)
    parser.add_argument("--cash", type=float, default=None)
    parser.add_argument("--holdings", default="")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()

    text = answer(args.question, args.cash, args.holdings)
    out = ROOT / "reports" / "conversation" / "latest_answer.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    result = {"output": str(out), "question": args.question}
    print(text)
    if args.push:
        push_result = send("feishu", build_question_message(args.question), dry_run=False)
        result["push"] = push_result
        print("\n---\n飞书已推送")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
