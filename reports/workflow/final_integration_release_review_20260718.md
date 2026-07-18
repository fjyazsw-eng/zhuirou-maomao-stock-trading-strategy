# 股票AI交易助手第六轮：联合演练、最小修复、封版与发布准备

生成日期：2026-07-18

本轮原则：先演练，后修复；只修复演练暴露的入口、状态、路径、历史和敏感信息断点；不修改交易策略、评分、A/B 买点、100 股规则、持仓卖出规则、系统性风险核心规则或六爻映射。

## 1. 联合演练范围

使用固定、透明、可重复的测试数据，在独立临时目录运行，不覆盖真实 `reports/workflow/current_workflow_state.json`。

覆盖范围：

- 周末：setup、status、现实分析、人工六爻输入、六爻校准、周度策略。
- 周一至周四：前夜计划、盘中否决、执行记录、收盘复盘、进入下一交易日前夜。
- 周五：前夜计划、盘中否决、执行记录、收盘复盘、周度复盘、下一周初始化。
- 五个完整场景：普通震荡周、系统性风险周、反转确认但不立即买入、反转失败、数据异常。
- 跨 Codex 冷启动。
- 十项故障恢复。
- 状态与历史一致性。
- GitHub 发布前安全检查。

## 2. 新增或修改文件

新增：

- `scoring_system/workflow_release_drill.py`
- `tests/test_final_integration_release.py`
- `docs/WORKFLOW_ARCHITECTURE.md`
- `docs/RELEASE_CHECKLIST.md`
- `CHANGELOG.md`
- `VERSION`
- `reports/workflow/final_integration_release_review_20260718.md`

修改：

- `scoring_system/workflow_orchestrator.py`
- `PROJECT_CONTEXT.md`
- `tests/test_portable_startup.py`
- `tests/test_realtime_watch_monitor.py`

## 3. 完整周度流程结果

普通震荡周演练通过。

- 处理交易日：`20260720`、`20260721`、`20260722`、`20260723`、`20260724`
- 周末允许谨慎试错。
- 六爻中性，未升级现实策略。
- 周一生成首选和替补。
- 盘中只检查首选和替补，未生成第三只股票。
- 首选通过后仅记录 `BUY_PRIMARY_100` 演练动作，不代表真实下单。
- 每日均有前夜、盘中、执行、收盘记录。
- 周五生成周度复盘记录。
- 下一周状态重置为 `WEEKEND_REALITY_PENDING`。
- 周归档存在，历史记录未覆盖。

## 4. 五个场景结果

| 场景 | 结果 | 核心检查 |
| --- | --- | --- |
| A 普通震荡周 | PASS | 每日循环正常；无第三只股票；历史记录独立保存 |
| B 系统性风险周 | PASS | 总闸开启；六爻偏强无法解除；候选挂起；不换股推荐；不自动清仓 |
| C 反转观察成功但未立即买入 | PASS | 进入 `REVERSAL_CONFIRMED`；总闸未解除前仍输出 `NO_NEW_BUY_SYSTEMIC_RISK` |
| D 反转失败 | PASS | 进入 `REVERSAL_FAILED`；同日不允许重复试错 |
| E 数据异常 | PASS | 输出 `NO_BUY_DATA_UNRELIABLE`；停止后续交易步骤 |

## 5. 跨Codex冷启动结果

模拟新 clone 环境：

- 只有 example 配置。
- 无真实 workflow state。
- 无真实 Token。
- 读取入口为 `PROJECT_CONTEXT.md`、`WORKFLOW_QUICKSTART.md`、`skills/stock-ai-workflow-controller/SKILL.md`。

结果：

- 缺 Token 时 setup：`NOT_READY`
- 配置 Token 并初始化 example 状态后 setup：`READY`
- 正式入口识别：`scripts/run_project.py`
- 不需要历史聊天。
- 不暴露完整 Token。
- 不依赖本机绝对路径。
- 当前阶段：`WEEKEND_REALITY_PENDING`
- 下一步：`weekend`

## 6. 故障恢复结果

| 故障 | 结果 |
| --- | --- |
| workflow state JSON 损坏 | 已报告，未自动覆盖原文件 |
| 当前阶段非法 | 已报告 |
| 六爻输入过期 | 当前策略忽略过期结果 |
| 同一六爻问题重复录入 | 已报错 |
| 前夜计划缺失时直接盘中检查 | 已报告为流程断点 |
| 当日系统性风险已锁定后再次运行 | 风险不降低，锁定不自动解除 |
| 历史报告目录不可写 | 已报告 |
| 核心模块导入失败 | setup 返回 `NOT_READY` |
| Token 缺失 | setup 返回 `NOT_READY` |
| 网络接口超时 | setup 返回警告或失败，不静默跳过 |

## 7. 状态和历史一致性

检查结果：

- current state 与演练 history 使用独立目录，未覆盖真实状态。
- 同一交易日同类历史记录重复写入时不再覆盖旧文件。
- 每日记录按交易日目录隔离。
- 周五复盘后生成周归档。
- 下一周初始化保留上周归档引用。
- 六爻风险窗口按日期参与校准。
- 系统性风险锁定日期保留。
- 解锁审核不覆盖原锁定原因。
- example 状态可用于初始化，但不会被当作真实状态继续交易。

## 8. 发现的问题

演练暴露的实际问题：

1. 同一天同类 history 记录重复写入会覆盖旧文件。
2. 故障恢复演练在隔离目录不存在时无法启动。
3. `PROJECT_CONTEXT.md` 曾包含真实持仓明细，不适合发布。
4. 测试夹具中曾保留真实持仓名称和成本。
5. 安全扫描最初会把空 Token 占位符和默认 100 股误报为疑似敏感项。
6. 本机 `git` 命令当前不可用。

## 9. 实际修复的问题

已修复：

- `record_history` 增加重复文件后缀，防止历史记录覆盖。
- `workflow_release_drill` 自动创建隔离输出目录。
- `PROJECT_CONTEXT.md` 脱敏真实持仓清单。
- 盯盘测试夹具改为虚拟持仓名称和非真实成本。
- 安全扫描规则收窄为非空、非占位密钥和更明确的持仓明细字段。
- 新增封版文档、版本号、发布清单和架构说明。

未修改：

- 市场评分。
- 板块评分。
- 选股逻辑。
- A/B 买点。
- 100 股规则。
- 持仓卖出规则。
- 系统性风险阈值。
- 六爻映射。
- 反转确认标准。

## 10. 未修复的策略候选问题

本轮只记录，不修：

- 真实市场多周连续运行后的准确率统计仍需实盘只读观察积累。
- 系统性风险和反转观察仍需更多真实截面验证。
- Tushare 权限、积分、限流和东方财富连接稳定性仍受外部环境影响。
- 历史报告是否适合公开提交仍需人工逐份脱敏复核。

## 11. 全量测试结果

测试命令：

`powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 -m pytest -q`

结果：

- `134 passed`

工作流相关回归：

- `78 passed`

封版专项：

- `9 passed`

setup：

- `READY`
- Token 只以掩码显示。
- 东方财富连接通过。
- Tushare endpoint 连接通过。
- workflow state 有效。

status：

- 当前阶段：`WEEKEND_REALITY_PENDING`
- 当前交易日：`20260717`
- 下一步：`weekend`

## 12. 安全检查结果

safe_to_commit_files：

- `README.md`
- `PROJECT_CONTEXT.md`
- `WORKFLOW_QUICKSTART.md`
- `docs/MIGRATION_GUIDE.md`
- `docs/WORKFLOW_ARCHITECTURE.md`
- `docs/RELEASE_CHECKLIST.md`
- `CHANGELOG.md`
- `VERSION`
- `.env.example`
- `config/project_config.example.yaml`
- `reports/workflow/current_workflow_state.example.json`
- `skills/stock-ai-workflow-controller/SKILL.md`
- `scripts/run_project.py`
- `scripts/run_setup_check.py`

ignored_sensitive_files：

- `.env`
- `reports/workflow/current_workflow_state.json`
- `reports/workflow/current_workflow_state.md`
- `config/realtime_watchlist.json`
- `config/push_channels.json`
- `config/telegram_bot.json`
- `data/`
- `*.sqlite`
- `.cc-connect/`
- `.codex/`

suspicious_files：

- 当前候选提交文件未发现明确疑似完整密钥、真实持仓明细或本机绝对路径。

manual_review_required：

- `reports/workflow/*.md` 历史报告发布前仍需人工确认不含真实持仓和完整密钥。
- `PROJECT_CONTEXT.md` 仍包含历史项目事实，公开发布前需按目标仓库范围人工复核。

## 13. GitHub发布清单

发布清单已生成：`docs/RELEASE_CHECKLIST.md`

关键状态：

- 全量测试通过：是
- setup 通过：是
- 五种联合演练通过：是
- 跨 Codex 冷启动通过：是
- 故障恢复演练通过：是
- example 配置脱敏：是
- 真实状态未作为示例提交：是
- Token 未进入示例配置：是
- 文档命令有效：是
- VERSION 已更新：是
- CHANGELOG 已更新：是
- Git 状态已审查：受限，本机 `git` 命令不可用
- 是否适合标记 rc1：是

## 14. 当前版本号

`1.0.0-rc1`

## 15. 是否建议标记 v1.0.0-rc1

建议标记 `v1.0.0-rc1`。

理由：

- 六轮工作流能力已形成闭环。
- 固定优先级和禁止事项已落到总控 Skill、文档和测试。
- 联合演练、冷启动、故障恢复和全量测试均通过。
- 本轮发现的非策略断点已最小修复。

## 16. 是否建议提交Git

建议提交 Git，但不是现在自动提交。

原因：

- 本轮默认不提交 Git。
- 本机当前 `git` 命令不可用，无法完成可靠的 `git status` 和提交前 diff 审查。
- 提交前仍需人工复核历史报告、真实状态和私密配置没有进入待提交清单。

## 17. 后续真实试运行建议

建议下一步进入只读真实试运行：

1. 连续两周使用 `scripts/run_project.py status` 和 `next` 驱动流程。
2. 每周末只用最新完整交易日生成现实分析。
3. 六爻仅人工输入结构化结论，并确认只降级。
4. 每个交易日只检查前夜首选和替补。
5. 系统性风险总闸触发后，当日不再新增买入。
6. 收盘后记录持仓动作、盘中否决价值和错失机会。
7. 周五复盘统计现实判断、六爻校准和盘中否决的实际价值。

最终结论：

可以作为 `v1.0.0-rc1` 候选发布版进入真实只读试运行；GitHub 提交前需补做 Git 状态审查和历史报告人工脱敏复核。
