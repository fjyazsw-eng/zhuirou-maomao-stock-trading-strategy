# 股票AI交易助手第五轮：一键启动、总控Skill与跨Codex迁移审查

生成日期：2026-07-18

本轮范围：只建立便携启动、总控 Skill、迁移文档、环境检查和统一命令入口。不新增交易策略，不修改评分、A/B 买点、100 股规则、持仓规则、系统性风险规则、六爻规则和工作流业务逻辑。

## 1. 现有入口审查

### 可以复用

- 项目总上下文：`PROJECT_CONTEXT.md`
- 项目说明：`README.md`、`README_PORTABLE.md`、`SETUP.md`
- 依赖入口：`requirements.txt`、`requirements-dev.txt`、`pyproject.toml`
- Python 启动包装：`scripts/run_project_python.ps1`
- 已有工作流入口：`scripts/run_workflow.py`
- 健康检查：`scripts/health_check.py`
- 已有 Skill：`skills/stock_strategy_lab/SKILL.md`
- 四轮工作流核心模块：
  - `scoring_system/workflow_state.py`
  - `scoring_system/systemic_risk_gate.py`
  - `scoring_system/hexagram_calibration.py`
  - `scoring_system/workflow_orchestrator.py`

### 需要合并或统一

- 工作流启动应统一到 `scripts/run_project.py`，底层继续复用 `scripts/run_workflow.py` 和 `workflow_orchestrator.py`。
- 新 Codex 接手说明应统一到 `PROJECT_CONTEXT.md`、`WORKFLOW_QUICKSTART.md`、`skills/stock-ai-workflow-controller/SKILL.md`。

### 存在重复

- `scripts/run_daily_workflow.py`
- `scripts/run_workflow_status.py`
- `scripts/run_workflow_state_tool.py`
- `scripts/run_workflow.py`

这些文件仍可保留为历史或底层入口，但不建议作为新 Codex 的第一入口。

### 不适合作为正式入口

- 单点日报、单点状态、单点盯盘脚本不适合作为总入口。
- `README_PORTABLE.md` 含历史便携说明，可参考，但不作为第五轮后的唯一正式入口。

### 敏感信息检查

- `.env` 存在但未读取完整内容，环境检查只输出 Token 是否存在和掩码。
- `PROJECT_CONTEXT.md` 已脱敏真实持仓监控示例。
- `reports/workflow/current_workflow_state.json` 被视为本地真实状态，已加入忽略规则。
- 私密消息配置、真实状态、本地缓存和本机运行目录不应提交 GitHub。

## 2. 新增或修改文件

### 新增

- `skills/stock-ai-workflow-controller/SKILL.md`
- `WORKFLOW_QUICKSTART.md`
- `docs/MIGRATION_GUIDE.md`
- `scoring_system/portable_setup_check.py`
- `scripts/run_setup_check.py`
- `scripts/run_project.py`
- `config/project_config.example.yaml`
- `reports/workflow/current_workflow_state.example.json`
- `tests/test_portable_startup.py`
- `reports/workflow/portable_startup_review_20260718.md`

### 修改

- `.gitignore`
- `PROJECT_CONTEXT.md`

## 3. 总控Skill结构

新增总控 Skill：`skills/stock-ai-workflow-controller/SKILL.md`。

职责：

- 判断当前工作流阶段。
- 读取状态。
- 决定下一步调用什么入口。
- 固定优先级。
- 指定禁止跳过的步骤。
- 指定异常停止条件。
- 指定输出格式。
- 指定不得修改的模块和规则。

固定优先级：

1. 数据可靠性
2. 系统性风险总闸
3. 现实市场分析
4. 人工六爻只降级校准
5. 前夜候选
6. 盘中否决
7. 持仓管理
8. 复盘

明确禁止：

- 六爻升级现实结论。
- 六爻解除系统性风险总闸。
- 总闸未解除前反转买入。
- 盘中生成第三只股票。
- 自动交易、真实下单、连接真实券商账户。
- 使用未来数据倒灌。
- 为了让测试或历史截面通过而事后修改阈值。

## 4. PROJECT_CONTEXT内容

`PROJECT_CONTEXT.md` 已补充第五轮后的正式版本信息：

- 当前正式工作流能力。
- 统一入口。
- 数据源与边界。
- 工作流阶段。
- 关键模块。
- 固定优先级。
- 迁移边界。
- 新 Codex 启动提示词。

同时将真实持仓监控示例改为“以本地私密配置为准”，避免公开文档记录真实持仓和成本。

## 5. QUICKSTART内容

`WORKFLOW_QUICKSTART.md` 面向第一次接触项目的人或新 Codex，包含：

- 项目用途。
- 环境要求。
- 第一次安装。
- Token 配置。
- 环境检查。
- 查看当前阶段。
- 运行下一步。
- 周末现实分析。
- 前夜计划。
- 盘中否决。
- 收盘复盘。
- 周五周报。
- 常见错误。
- 新电脑迁移。
- GitHub 恢复。
- 安装验证。
- 新 Codex 固定启动口令。
- 三个常用口令。

## 6. setup检查项

新增 `scoring_system/portable_setup_check.py` 与 `scripts/run_setup_check.py`。

检查项：

- Python 版本。
- 项目路径。
- requirements 文件。
- `.env.example`。
- Tushare 是否安装。
- Token 是否存在，且只显示掩码。
- 东方财富连接。
- Tushare endpoint 连接。
- 核心模块导入。
- 总控 Skill 是否存在。
- 工作流状态文件是否存在。
- 工作流状态结构是否有效。
- 编排器模块是否可导入。
- 示例配置是否存在。
- 报告目录是否可写。
- 测试目录是否存在。

输出状态只使用：

- `READY`
- `READY_WITH_WARNINGS`
- `NOT_READY`

并列出：

- `passed_checks`
- `warnings`
- `failed_checks`
- `recommended_actions`

## 7. 统一启动命令

新增 `scripts/run_project.py`。

支持命令：

- `setup`
- `status`
- `next`
- `validate`
- `weekend-start`
- `night-plan`
- `intraday-check`
- `closing-review`
- `weekly-review`
- `show-help`

实现原则：

- 只做路由。
- 复用 `scoring_system.workflow_orchestrator`。
- 不重复实现业务编排逻辑。
- `setup/status/validate/show-help` 为安全命令。
- 其他业务命令在环境 `NOT_READY` 时直接阻断。
- 非法命令不修改状态。

## 8. GitHub迁移方案

新增 `docs/MIGRATION_GUIDE.md`，覆盖：

- 复制项目。
- GitHub clone。
- 必须保留的文件。
- 不能提交的文件。
- Token 重新配置。
- workflow state 恢复。
- 依赖验证。
- 测试运行。
- 新 Codex 启动。
- Windows 路径差异。
- Linux/macOS 使用方式。
- Python 虚拟环境。
- 东方财富或 Tushare 连接失败处理。
- 历史报告迁移。
- GitHub 安全检查。

## 9. 敏感信息保护

`.gitignore` 已覆盖：

- `.env`
- `.venv/`
- Python 缓存
- pytest 缓存
- SQLite 数据库
- `data/`
- `logs/`
- `runtime/`
- `config/realtime_watchlist.json`
- `config/push_channels.json`
- `config/telegram_bot.json`
- `.cc-connect/`
- `.codex/`
- `reports/workflow/current_workflow_state.json`
- `reports/workflow/current_workflow_state.md`
- `reports/workflow/history/`

同时允许保留：

- 正式文档。
- Skill。
- 代码。
- 测试。
- 示例配置。
- `reports/workflow/*.md`
- `reports/workflow/current_workflow_state.example.json`

## 10. 示例配置

新增或确认：

- `.env.example`
- `config/project_config.example.yaml`
- `reports/workflow/current_workflow_state.example.json`

检查结果：

- 示例配置不含真实 Token。
- 示例状态不含真实持仓。
- 示例状态不含真实账户。
- 示例状态不依赖本机绝对路径。

## 11. 单元测试和全量测试

新增测试：`tests/test_portable_startup.py`

覆盖：

1. 总控 Skill 存在。
2. 快速启动文档存在。
3. 项目上下文文件存在。
4. setup 检查成功时输出 `READY`。
5. Token 缺失时输出 `NOT_READY` 或明确警告。
6. 关键模块导入失败时输出 `NOT_READY`。
7. workflow state 损坏时输出 `NOT_READY`。
8. 环境未通过时业务命令被阻止。
9. `status` 可以只读运行。
10. `next` 复用原编排器。
11. 新入口不因非法命令修改业务状态。
12. `.gitignore` 覆盖敏感配置。
13. 示例配置不含真实 Token。
14. 示例状态不含真实持仓。
15. 文档中的命令实际存在。
16. 新 Codex 启动口令能够找到对应文件。
17. Windows 路径不是唯一支持环境。
18. 新克隆项目可以使用示例状态完成初始化检查。

测试结果：

- `tests/test_portable_startup.py`：16 passed
- 四轮相关回归：69 passed
- 全量测试：125 passed

## 12. 三个冷启动演示

### 场景A：当前本机完整环境

运行统一入口 `setup`：

- 结果：`READY`
- Python：3.12.13
- 核心模块导入：通过
- Token：存在，仅掩码显示
- workflow state：有效
- 报告目录：可写
- 东方财富连接：通过
- Tushare endpoint 连接：通过

运行统一入口 `status`：

- 当前阶段：`WEEKEND_REALITY_PENDING`
- 当前交易日：`20260717`
- 缺失步骤：周末现实分析、六爻人工输入、周度策略、前夜计划
- 系统性风险等级：空
- 新买锁定：false
- 六爻有效：false
- 反转观察状态：`NONE`
- 下一步：`weekend`

### 场景B：缺少Token的模拟新环境

模拟清空 Tushare Token 后运行 setup：

- 结果：`NOT_READY`
- 失败项：`Tushare token missing`
- 建议动作：复制 `.env.example` 为 `.env`，配置 `TUSHARE_REPLAY_API_KEY` 或 `TUSHARE_TOKEN`

继续尝试业务命令 `night-plan`：

- 结果：被阻断
- 阻断原因：环境 `NOT_READY`

### 场景C：新克隆项目

用临时目录模拟新克隆项目：

- 无本地真实状态。
- 使用示例 workflow state 生成初始状态。
- 使用示例配置。
- 使用占位 Token 模拟可配置环境。
- 跳过网络检查。

结果：

- setup 状态：`READY`
- 无失败项。
- 无警告项。
- `recommended_actions` 不包含本机绝对路径。

## 13. 已知边界

- `setup` 只验证连接可达和模块可导入，不代表 Tushare 当前积分权限覆盖全部业务接口。
- `setup` 不拉取行情明细，不判断市场强弱，不生成候选。
- `run_project.py` 是路由入口，不替代底层编排器。
- 新克隆模拟使用最小夹具和示例状态，不代表真实历史报告完整迁移。
- 当前未自动创建 GitHub 仓库，也未提交 Git。
- 当前不自动修复损坏状态，只报告并给出恢复建议。

## 14. 是否建议进入第六轮联合演练与封版

建议进入第六轮联合演练与封版。

理由：

- 第五轮便携入口、总控 Skill、快速启动、迁移文档、示例配置和敏感信息保护已经具备。
- 新入口未改动交易策略和评分逻辑。
- 单元测试、四轮相关回归和全量测试均通过。
- 下一轮适合用完整周末到周五链路做只读联合演练，检查真实使用中的顺序、报告衔接和异常停止点。
