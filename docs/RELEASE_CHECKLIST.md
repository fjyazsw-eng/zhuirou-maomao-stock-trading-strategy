# v1.0.0-rc1 发布清单

## 必查项

- [x] 全量测试通过。
- [x] setup 为 `READY` 或明确警告。
- [x] 五种联合演练通过。
- [x] 跨 Codex 冷启动通过。
- [x] 故障恢复演练通过。
- [x] example 配置已脱敏。
- [x] 真实状态未作为示例提交。
- [x] Token 未进入示例配置。
- [x] 文档命令有效。
- [x] VERSION 已更新为 `1.0.0-rc1`。
- [x] CHANGELOG 已更新。
- [ ] Git 状态已审查。
- [ ] 待提交文件已人工列出。
- [ ] 不应提交文件已人工列出。
- [x] 适合标记 `v1.0.0-rc1` 候选发布版。

## 待提交文件候选

- `VERSION`
- `CHANGELOG.md`
- `PROJECT_CONTEXT.md`
- `WORKFLOW_QUICKSTART.md`
- `docs/MIGRATION_GUIDE.md`
- `docs/WORKFLOW_ARCHITECTURE.md`
- `docs/RELEASE_CHECKLIST.md`
- `.env.example`
- `.gitignore`
- `config/project_config.example.yaml`
- `reports/workflow/current_workflow_state.example.json`
- `skills/stock-ai-workflow-controller/SKILL.md`
- `scoring_system/portable_setup_check.py`
- `scoring_system/workflow_release_drill.py`
- `scripts/run_project.py`
- `scripts/run_setup_check.py`
- `tests/test_portable_startup.py`
- `tests/test_final_integration_release.py`
- `reports/workflow/portable_startup_review_20260718.md`
- `reports/workflow/final_integration_release_review_20260718.md`

## 不应提交文件

- `.env`
- `.venv/`
- `data/`
- `*.sqlite`
- `reports/workflow/current_workflow_state.json`
- `reports/workflow/current_workflow_state.md`
- `reports/workflow/history/`
- `config/realtime_watchlist.json`
- `config/push_channels.json`
- `config/telegram_bot.json`
- `.cc-connect/`
- `.codex/`
- 任何含真实持仓、真实成本、完整 Token、Webhook 或本机账号的文件

## 发布判断

当前建议：可以作为 `v1.0.0-rc1` 候选发布准备，但提交前仍需人工复核 Git 待提交清单和历史报告脱敏情况。
