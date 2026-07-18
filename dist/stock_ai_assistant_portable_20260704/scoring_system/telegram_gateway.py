from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from scoring_system.conversation_entry import answer
from scoring_system.push_gateway import clean_user_text


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "telegram_bot.json"
CONFIG_EXAMPLE = ROOT / "config" / "telegram_bot.example.json"
REPORT_DIR = ROOT / "reports" / "telegram"
OFFSET_PATH = REPORT_DIR / "telegram_offset.json"
KNOWN_CHATS_PATH = REPORT_DIR / "known_chat_ids.json"


def load_config() -> dict[str, Any]:
    path = CONFIG_PATH if CONFIG_PATH.exists() else CONFIG_EXAMPLE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def telegram_config() -> dict[str, Any]:
    return load_config().get("telegram", {})


def llm_config() -> dict[str, Any]:
    cfg = load_config()
    if "llm" in cfg:
        return cfg.get("llm", {})
    return cfg.get("openai", {})


def bot_token(cfg: dict[str, Any]) -> str:
    env_name = cfg.get("bot_token_env", "TELEGRAM_BOT_TOKEN")
    return os.environ.get(env_name, "") or cfg.get("bot_token", "")


def llm_api_key(cfg: dict[str, Any]) -> str:
    env_name = cfg.get("api_key_env", "OPENAI_API_KEY")
    return os.environ.get(env_name, "") or cfg.get("api_key", "")


def api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    if not parsed.get("ok"):
        raise RuntimeError(raw[:1000])
    return parsed


def read_offset() -> int:
    if not OFFSET_PATH.exists():
        return 0
    try:
        return int(json.loads(OFFSET_PATH.read_text(encoding="utf-8")).get("offset", 0))
    except Exception:
        return 0


def write_offset(offset: int) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    OFFSET_PATH.write_text(
        json.dumps({"offset": offset, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def remember_chat_id(chat_id: int) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"chat_ids": [], "updated_at": ""}
    if KNOWN_CHATS_PATH.exists():
        try:
            payload = json.loads(KNOWN_CHATS_PATH.read_text(encoding="utf-8"))
        except Exception:
            payload = {"chat_ids": [], "updated_at": ""}
    chat_ids = {str(x) for x in payload.get("chat_ids", [])}
    chat_ids.add(str(chat_id))
    KNOWN_CHATS_PATH.write_text(
        json.dumps(
            {"chat_ids": sorted(chat_ids), "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def allowed_chat(chat_id: int, cfg: dict[str, Any]) -> bool:
    allowed = cfg.get("allowed_chat_ids") or []
    if not allowed:
        return True
    return str(chat_id) in {str(x) for x in allowed}


def compact_answer(question: str) -> str:
    cash = extract_cash(question)
    full = answer(question, cash=cash)
    relevant_context = build_relevant_context(question)
    if relevant_context:
        full = f"{full}\n\n## 针对本次问题补充的专项材料\n{relevant_context}"
    sections = []
    keep = False
    for line in full.splitlines():
        stripped = line.strip()
        if stripped.startswith("## 这次提问还差什么"):
            keep = True
        elif stripped.startswith("## 关键依据摘录"):
            keep = True
        elif stripped.startswith("## 事件与资金代理摘录"):
            keep = False
        elif stripped.startswith("## 事件层摘录"):
            keep = False
        elif stripped.startswith("## 持仓/空仓建议摘录"):
            keep = False
        elif stripped.startswith("## 回答框架"):
            keep = True
        if keep and stripped:
            sections.append(stripped.replace("#", "").strip())
    direct = build_smart_view(question, cash, full)
    if llm_is_ready():
        text = clean_user_text(direct.strip())
    else:
        text = clean_user_text("\n".join([direct, *sections[:42]]).strip())
    if not text:
        text = clean_user_text(full[:2600])
    header = [
        "股票AI量化助手",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"问题：{question}",
        "",
    ]
    footer = [
        "",
        "分数参考：大盘70+环境较好；板块75+偏强；个股78+才算更适合参与；K线低吸70+才算承接较强。",
        "边界：仅作辅助分析，不自动交易，不替代最终决策。",
    ]
    return "\n".join(header) + text + "\n".join(footer)


def build_smart_view(question: str, cash: float | None, full_answer: str) -> str:
    fallback = build_direct_view(question, cash)
    cfg = llm_config()
    if not cfg.get("enabled", False):
        return fallback + "\n- 智能层：未开启，当前使用本地规则总结。"
    key = llm_api_key(cfg)
    if not key:
        provider = cfg.get("provider", "大模型")
        return fallback + f"\n- 智能层：未配置 {provider} API Key，当前使用本地规则总结。"
    try:
        result = call_compatible_chat_summarizer(key, cfg, question, cash, full_answer)
    except Exception as exc:
        return fallback + f"\n- 智能层：调用失败，已退回本地规则总结。原因：{type(exc).__name__}"
    return result.strip() or fallback


def llm_is_ready() -> bool:
    cfg = llm_config()
    return bool(cfg.get("enabled", False) and llm_api_key(cfg))


def call_compatible_chat_summarizer(key: str, cfg: dict[str, Any], question: str, cash: float | None, full_answer: str) -> str:
    model = cfg.get("model", "deepseek-chat")
    base_url = str(cfg.get("base_url", "https://api.deepseek.com")).rstrip("/")
    url = base_url
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1"):
            url = f"{url}/chat/completions"
        else:
            url = f"{url}/v1/chat/completions"
    payload = {
        "model": model,
        "temperature": float(cfg.get("temperature", 0.2)),
        "max_tokens": int(cfg.get("max_tokens", 900)),
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是A股量化辅助分析助手。只基于给定数据回答，不编造实时行情、政策、公告或资金。"
                    "必须用中文，先给白话结论，再列依据、风险、下一步观察点。"
                    "如果问题问板块是低吸、回调、退潮还是承接，要优先使用板块状态、退潮预警、资金代理、K线承接材料。"
                    "不要因为某板块没出现在优势榜就说没有数据；如果专项材料里有该板块预警或状态，必须引用专项材料。"
                    "涉及具体板块时，不要混用其他相邻板块的代码、分数或资金数据；例如半导体只使用半导体801081.SI的分数。"
                    "不能给确定性买卖指令，不能说保证上涨或必须买卖。"
                    "如果数据是旧报告，要明确说数据时间可能滞后。"
                    "控制在700字以内，适合手机阅读。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{question}\n"
                    f"识别资金：{cash if cash is not None else '未识别'}\n\n"
                    "本地模型原始材料如下：\n"
                    f"{clean_user_text(full_answer[:5200])}"
                ),
            },
        ],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    parsed = json.loads(raw)
    choices = parsed.get("choices", [])
    if choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content
    return ""


def build_relevant_context(question: str) -> str:
    keywords = detect_context_keywords(question)
    if not keywords:
        return ""
    parts: list[str] = []
    structured = structured_sector_context(question)
    if structured:
        parts.append(f"### 命中板块结构化摘要\n{structured}")
    paths = []
    if not structured:
        paths.extend(
            [
                ("板块状态识别", ROOT / "reports" / "regime" / "sector_regime_20260702.md"),
                ("退潮预警", ROOT / "reports" / "alerts" / "sector_alerts_20260702.md"),
            ]
        )
    if not structured:
        paths.extend(
            [
                ("科技板块资金检查", ROOT / "reports" / "tech_sector_funds_check_20260701.json"),
                ("科技板块阶段检查", ROOT / "reports" / "tech_sector_end_check_20260701.json"),
                ("科技板块融资检查", ROOT / "reports" / "tech_sector_margin_check_20260630.json"),
            ]
        )
    for title, path in paths:
        excerpt = excerpt_file(path, keywords, context=3, max_lines=36)
        if excerpt:
            parts.append(f"### {title}\n{excerpt}")
    if is_sector_status_question(question):
        parts.append(
            "### 判定口径\n"
            "- 低吸：需要板块未退潮、个股或板块有承接、低吸评分/承接证据较强。\n"
            "- 短期回调：板块层级仍在强势或轮动区，主要受大盘压制，未连续跌入弱势。\n"
            "- 退潮：强势区快速跌入弱势/退潮区，或已经处于弱势且继续恶化。\n"
            "- 承接：需要资金、K线、次日修复或板块同步止跌共同确认；单日下跌后不能凭感觉认定有承接。"
        )
    return "\n\n".join(parts)


def structured_sector_context(question: str) -> str:
    text = question or ""
    targets: list[tuple[str, str]] = []
    if "半导体" in text:
        targets.append(("801081.SI", "半导体"))
    if "电子化学品" in text:
        targets.append(("801086.SI", "电子化学品Ⅱ"))
    if "光学光电子" in text or "光学" in text:
        targets.append(("801084.SI", "光学光电子"))
    if not targets:
        return ""
    lines: list[str] = []
    regime_path = ROOT / "reports" / "regime" / "sector_regime_20260702.json"
    alert_path = ROOT / "reports" / "alerts" / "sector_alerts_20260702.json"
    regime_rows = load_json_rows(regime_path, "items")
    alert_rows = load_json_rows(alert_path, "alerts")
    for code, name in targets:
        lines.append(f"- 目标板块：{name} {code}")
        for row in regime_rows:
            if row.get("index_code") == code:
                lines.append(
                    f"  - 当前状态：{row.get('trade_date')} 分数 {row.get('score')}，级别 {row.get('grade')}；"
                    f"前一日 {row.get('prev_date')} 分数 {row.get('prev_score')}，变化 {row.get('score_change')}；"
                    f"状态 {row.get('state')}；原因：{row.get('reason')}"
                )
                break
        matched_alerts = [row for row in alert_rows if row.get("index_code") == code]
        for row in matched_alerts[:3]:
            lines.append(
                f"  - 预警：{row.get('prev_date')} {row.get('prev_score')}/{row.get('prev_grade')} -> "
                f"{row.get('curr_date')} {row.get('curr_score')}/{row.get('curr_grade')}；"
                f"等级 {row.get('level')}；原因：{row.get('reason')}"
            )
    return "\n".join(lines)


def load_json_rows(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    rows = payload.get(key, [])
    return rows if isinstance(rows, list) else []


def detect_context_keywords(question: str) -> list[str]:
    text = question or ""
    keyword_map = {
        "半导体": ["半导体", "半导体材料"],
        "科技": ["半导体", "电子化学品", "光学光电子", "元件", "计算机设备", "半导体材料"],
        "电子": ["半导体", "电子化学品", "光学光电子", "元件"],
        "光学": ["光学光电子"],
        "化学品": ["电子化学品"],
        "计算机": ["计算机设备"],
    }
    found: list[str] = []
    for trigger, values in keyword_map.items():
        if trigger in text:
            found.extend(values)
    return sorted(set(found))


def is_sector_status_question(question: str) -> bool:
    text = question or ""
    return any(k in text for k in ["板块", "低吸", "回调", "退潮", "承接", "走弱", "修复", "风险"])


def excerpt_file(path: Path, keywords: list[str], context: int = 2, max_lines: int = 30) -> str:
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    selected: list[str] = []
    seen: set[int] = set()
    for i, line in enumerate(lines):
        if any(k in line for k in keywords):
            start = max(0, i - context)
            end = min(len(lines), i + context + 1)
            for idx in range(start, end):
                if idx not in seen:
                    selected.append(lines[idx])
                    seen.add(idx)
                if len(selected) >= max_lines:
                    break
        if len(selected) >= max_lines:
            break
    return "\n".join(selected[:max_lines]).strip()


def read_report_text(limit: int = 5000) -> str:
    path = ROOT / "reports" / "latest_market_decision_report.md"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def find_report_line(prefix: str) -> str:
    for line in read_report_text().splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped
    return ""


def build_direct_view(question: str, cash: float | None) -> str:
    intent = "持仓" if any(k in question for k in ["持有", "持仓", "成本", "减仓", "加仓"]) else "空仓" if any(k in question for k in ["空仓", "资金", "现金"]) else "单票/板块"
    horizon = "短线" if "短线" in question else "中线" if "中线" in question else "长线" if "长线" in question else "未说明"
    weather = find_report_line("- 大盘天气评分") or "- 大盘天气评分：缺失"
    up = find_report_line("- 上涨家数")
    down = find_report_line("- 下跌家数")
    cash_line = f"- 你的资金：{cash:,.0f} 元" if cash is not None else "- 你的资金：未识别"
    if intent == "空仓" and horizon == "短线":
        conclusion = "白话结论：按当前旧报告环境，短线空仓不适合急着满仓进攻，更适合先观察强板块，等分歧承接确认后再考虑小仓试错。"
    elif intent == "持仓":
        conclusion = "白话结论：先看持仓所属板块是否退潮，再看个股是否放量下跌或跌破关键位置；当前回答先给风险框架，后续要接单票体检才会更准。"
    else:
        conclusion = "白话结论：先按大盘环境、板块强弱、个股位置、K线承接四步判断，不把单一分数当买卖指令。"
    lines = [
        "直接判断",
        conclusion,
        cash_line,
        f"- 你的周期：{horizon}",
        weather,
    ]
    if up:
        lines.append(up)
    if down:
        lines.append(down)
    return "\n".join(lines)


def extract_cash(text: str) -> float | None:
    normalized = (text or "").replace(",", "").replace("，", "")
    match = re.search(r"(?:资金|现金|本金)\s*([0-9]+(?:\.[0-9]+)?)\s*(万|万元|元)?", normalized)
    if not match:
        match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(万|万元)", normalized)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2) or ""
    if "万" in unit:
        value *= 10000
    return value


def split_text(text: str, max_chars: int) -> list[str]:
    max_chars = max(800, min(max_chars, 3900))
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        add_len = len(line) + 1
        if current and current_len + add_len > max_chars:
            parts.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += add_len
    if current:
        parts.append("\n".join(current))
    return parts


def send_message(token: str, chat_id: int, text: str, max_chars: int = 3000) -> None:
    for part in split_text(text, max_chars):
        api_call(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": part,
                "disable_web_page_preview": True,
            },
        )


def help_text() -> str:
    return "\n".join(
        [
            "股票AI量化助手已在线。",
            "",
            "你可以这样问：",
            "问：我现在空仓，资金5万，想做短线，今天适合出手吗？",
            "问：鼎龙股份现在怎么样，能不能低吸？",
            "问：我持有002468，成本15.80，1000股，要不要减仓？",
            "问：半导体这几天走弱，是回调还是退潮？",
            "",
            "建议带上：空仓/持仓、资金量、股票代码、成本、周期。",
        ]
    )


def handle_message(token: str, message: dict[str, Any], cfg: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if chat_id is None or not text:
        return {"handled": False, "reason": "不是文本消息"}
    remember_chat_id(int(chat_id))
    if not allowed_chat(int(chat_id), cfg):
        return {"handled": False, "reason": f"chat_id 未放行：{chat_id}"}

    if text in {"/start", "/help", "帮助", "模板"}:
        reply = help_text()
    elif text == "/id":
        reply = f"当前 chat_id：{chat_id}"
    else:
        question = text
        if text.startswith("问："):
            question = text[2:].strip()
        reply = compact_answer(question)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    latest = REPORT_DIR / "latest_telegram_reply.md"
    latest.write_text(reply, encoding="utf-8")

    if not dry_run:
        send_message(token, int(chat_id), reply, int(cfg.get("reply_max_chars", 3000)))
    return {"handled": True, "chat_id": chat_id, "text": text[:120], "dry_run": dry_run}


def poll_once(token: str, cfg: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    offset = read_offset()
    timeout = int(cfg.get("poll_timeout_seconds", 25))
    params = {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]}
    query = urllib.parse.urlencode({"offset": params["offset"], "timeout": params["timeout"]})
    url_method = f"getUpdates?{query}"
    updates = api_call(token, url_method).get("result", [])
    results = []
    next_offset = offset
    for update in updates:
        update_id = int(update.get("update_id", 0))
        next_offset = max(next_offset, update_id + 1)
        message = update.get("message") or {}
        results.append(handle_message(token, message, cfg, dry_run=dry_run))
    if next_offset != offset:
        write_offset(next_offset)
    return {"updates": len(updates), "results": results, "next_offset": next_offset}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Telegram 手机双向问答入口")
    parser.add_argument("--once", action="store_true", help="只检查一次新消息")
    parser.add_argument("--dry-run", action="store_true", help="生成回复但不发回 Telegram")
    parser.add_argument("--test-question", default="", help="本地测试问题，不连接 Telegram")
    args = parser.parse_args(argv)

    cfg = telegram_config()
    if args.test_question:
        print(compact_answer(args.test_question))
        return 0

    token = bot_token(cfg)
    if not token:
        print("Telegram Bot Token 未配置。请复制 config/telegram_bot.example.json 为 config/telegram_bot.json，并填写 bot_token。")
        return 2

    if args.once:
        print(json.dumps(poll_once(token, cfg, dry_run=args.dry_run), ensure_ascii=False, indent=2))
        return 0

    print("Telegram 双向助手已启动。保持这个窗口打开，手机发消息就会自动回复。")
    while True:
        try:
            result = poll_once(token, cfg, dry_run=args.dry_run)
            if result["updates"]:
                print(json.dumps(result, ensure_ascii=False))
        except KeyboardInterrupt:
            print("已停止。")
            return 0
        except Exception as exc:
            print(f"Telegram 轮询异常：{type(exc).__name__}: {exc}")
            time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
