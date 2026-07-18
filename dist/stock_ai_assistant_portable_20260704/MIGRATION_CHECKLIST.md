# 迁移检查清单

## 需要复制的内容

- `scoring_system/`
- `scripts/`
- `skills/`
- `config/` 中的非敏感模板文件
- `reports/` 中必要的最近报告和样例
- `requirements.txt`
- `README.md`
- `SETUP.md`
- `.env.example`
- 健康检查脚本
- 必要的数据库文件或数据重建说明

## 不应复制的内容

- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `.git/`
- `auth.json`
- 真实 `.env`
- 真实 `config.toml`
- API token
- cookie
- 浏览器登录态
- 大型临时缓存
- 无关下载文件
- `config/push_channels.json`
- `config/telegram_bot.json`

## 新电脑需要重新配置

- Tushare token
- Codex 登录
- Python 虚拟环境
- 飞书/TG webhook，如后续需要
- 本地路径
- 定时任务

## 迁移后验证

1. 进入项目根目录。
2. 运行 `python scripts/health_check.py`。
3. 确认 `skills/stock_strategy_lab/SKILL.md` 存在。
4. 确认能打开 `reports/latest_market_decision_dashboard.html`。
5. 确认没有真实 token 被复制到迁移包。
