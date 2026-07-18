from pathlib import Path
import json
import os


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "push_channels.json"
EXAMPLE = ROOT / "config" / "push_channels.example.json"


def main() -> int:
    path = CONFIG if CONFIG.exists() else EXAMPLE
    cfg = json.loads(path.read_text(encoding="utf-8"))
    feishu = cfg.get("feishu", {})
    env_name = feishu.get("webhook_env", "FEISHU_WEBHOOK")
    url = os.environ.get(env_name, "") or feishu.get("webhook_url", "")
    secret_env = feishu.get("secret_env", "FEISHU_SECRET")
    secret = os.environ.get(secret_env, "") or feishu.get("secret", "")
    result = {
        "config_file": str(path),
        "has_private_config": CONFIG.exists(),
        "enabled": bool(feishu.get("enabled")),
        "webhook_configured": bool(url),
        "webhook_looks_like_feishu": url.startswith("https://open.feishu.cn/open-apis/bot/v2/hook/"),
        "secret_configured": bool(secret),
        "next_step": "",
    }
    if not CONFIG.exists():
        result["next_step"] = "先把 push_channels.example.json 复制为 push_channels.json，再填 webhook_url"
    elif not url:
        result["next_step"] = "请填写飞书 webhook_url，或设置 FEISHU_WEBHOOK 环境变量"
    elif not result["webhook_looks_like_feishu"]:
        result["next_step"] = "webhook 地址不像飞书自定义机器人地址，请重新核对"
    else:
        result["next_step"] = "配置看起来可以测试发送"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
