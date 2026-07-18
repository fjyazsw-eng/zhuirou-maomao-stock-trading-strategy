# 迁移任务模板

## 迁移目标

将项目迁移到新电脑或新 Codex 环境。

## 必须复制

- `scoring_system/`
- `scripts/`
- `skills/`
- 非敏感配置模板
- 最近样例报告
- `requirements.txt`
- `SETUP.md`
- `.env.example`

## 禁止复制

- `.venv/`
- `__pycache__/`
- `.env`
- `auth.json`
- 真实 token
- cookie
- 浏览器登录态

## 验收

1. 运行 `python scripts/health_check.py`
2. 生成或打开最新看板
3. 确认无敏感信息
