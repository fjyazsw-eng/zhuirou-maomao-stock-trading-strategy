from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from scoring_system.push_gateway import build_test_message, build_question_message, build_daily_brief


def main() -> int:
    print("# 飞书提问卡片")
    print("")
    print("## 你可以这样问")
    print("- 我现在空仓，资金 5 万，怎么安排？")
    print("- 我有 002468，成本 15.80，怎么处理？")
    print("- 鼎龙股份能不能低吸？")
    print("")
    print("## 评分规则")
    print("- 大盘 70+：环境较好")
    print("- 板块 75+：强势板块")
    print("- 个股执行 78+：可以参与")
    print("- K线低吸 70+：承接较强")
    print("")
    print("## 测试消息")
    print(build_test_message())
    print("")
    print("## 问答示例")
    print(build_question_message("问：鼎龙股份现在怎么样，能不能低吸？"))
    print("")
    print("## 简报示例")
    print(build_daily_brief("20260702"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
