# 股票AI交易助手迁移与 GitHub 恢复指南

## 1. 如何复制项目

复制项目代码目录即可。不要复制 `.venv`、`.env`、本地数据库、私密消息配置或个人会话目录给别人。

推荐复制：

- `scoring_system/`
- `scripts/`
- `skills/`
- `docs/`
- `config/*.example.*`
- `.env.example`
- `requirements.txt`
- `requirements-dev.txt`
- `pyproject.toml`
- `PROJECT_CONTEXT.md`
- `WORKFLOW_QUICKSTART.md`

## 2. 如何从 GitHub clone

```powershell
git clone <repo-url>
cd <repo>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env
```

Linux/macOS：

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

## 3. 哪些文件必须保留

- 代码：`scoring_system/`、`scripts/`
- Skill：`skills/stock-ai-workflow-controller/`、`skills/stock_strategy_lab/`
- 文档：`PROJECT_CONTEXT.md`、`WORKFLOW_QUICKSTART.md`、`docs/MIGRATION_GUIDE.md`
- 示例配置：`.env.example`、`config/project_config.example.yaml`
- 示例状态：`reports/workflow/current_workflow_state.example.json`
- 测试：`tests/`

## 4. 哪些文件不能提交

- `.env`
- `.venv/`
- `data/`
- `*.sqlite`
- `config/push_channels.json`
- `config/telegram_bot.json`
- `config/realtime_watchlist.json`
- `.cc-connect/`
- `.codex/`
- `reports/workflow/current_workflow_state.json`
- 可能包含真实持仓、真实账户、完整 Token 或个人消息会话的文件

## 5. 如何重新配置 Token

复制 `.env.example` 为 `.env`。

填写任意一种可用凭据：

```text
TUSHARE_REPLAY_API_KEY=
TUSHARE_TOKEN=
TUSHARE_TOKEN_PRO=
```

不要把 Token 写进 README、报告、截图或 GitHub issue。

## 6. 如何恢复 workflow state

如果没有本地真实状态：

```powershell
copy reports\workflow\current_workflow_state.example.json reports\workflow\current_workflow_state.json
```

然后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py validate
```

真实状态可能包含个人操作记录，不建议提交到公共仓库。

## 7. 如何验证依赖

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py setup
```

## 8. 如何运行测试

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 -m pytest -q
```

## 9. 如何在新 Codex 中启动

对新 Codex 说：

```text
请先读取 PROJECT_CONTEXT.md、WORKFLOW_QUICKSTART.md 和 skills/stock-ai-workflow-controller/SKILL.md。运行环境检查，读取当前工作流状态，只告诉我当前阶段、缺失条件和下一步。不要修改评分、策略、阈值或状态，除非我明确要求。
```

## 10. Windows 路径差异

不要把本机绝对路径当成唯一路径。脚本默认从项目根目录推导路径。

Windows 推荐：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py status
```

Linux/macOS 可直接使用当前虚拟环境 Python：

```bash
.venv/bin/python scripts/run_project.py status
```

## 11. Python 虚拟环境

迁移时重新创建 `.venv`，不要复制旧虚拟环境。

如果默认 `python` 不可用，Windows 下先运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_codex_runtime_health.ps1
```

## 12. 东方财富或 Tushare 连接失败

- 东方财富失败：盘中临时判断不可用，不得输出盘中确认结论。
- Tushare 失败：正式日线、板块和推荐资格不可用，不得输出正式买入建议。
- Token 缺失：`setup` 应输出 `NOT_READY`。
- 网络失败不代表策略失败，只代表当前数据不可确认。

## 13. 如何迁移历史报告

可迁移：

- `reports/workflow/*.md`
- `reports/workflow/history/`
- 经脱敏的复盘报告

不要迁移或提交：

- 含真实持仓明细的状态文件
- 含完整 Token 或 webhook 的日志
- 本地缓存数据库

## 14. GitHub 安全检查

提交前至少运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py setup
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 -m pytest -q
```

并人工确认 `.env`、真实状态和私密配置未进入 Git。
