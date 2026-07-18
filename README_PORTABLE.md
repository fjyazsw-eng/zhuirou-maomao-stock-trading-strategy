# 股票AI交易助手可迁移部署包

## 1. 这个包是什么

这是“股票AI交易助手”的可迁移部署包，用于把当前项目迁移到新电脑或新 Codex 环境，快速恢复开发、报告生成和模型审查工作流。

## 2. 这个包不是什么

它不是自动交易系统，不包含真实交易账户，不包含真实 token，不保证盈利，不会自动下单。

## 3. 新电脑部署步骤

1. 解压压缩包。
2. 安装 Python 3.11 或 3.12。
3. 进入项目目录。
4. 创建虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

5. 安装依赖：

```powershell
pip install -r requirements.txt
```

6. 复制 `.env.example` 为 `.env`，填入自己的 Tushare token。
7. 放入数据库，默认位置为 `data/sqlite/market_120d.sqlite`；如果没有数据库，按健康检查提示重建。
8. 运行健康检查：

```powershell
python scripts/health_check.py
```

9. 生成报告：

```powershell
python scoring_system/hierarchy_report.py
```

10. 打开 HTML 看板：

```text
reports/latest_market_decision_dashboard.html
```

## 4. 第一条测试命令

```powershell
python scripts/health_check.py
```

## 5. 日常运行流程

部署完成后，可以先按最小日常流程检查系统是否可用：

```powershell
python scripts/check_daily_outputs.py
python scripts/run_daily_workflow.py
```

日常阅读顺序请看：

- `DAILY_WORKFLOW.md`
- `REPORT_READING_GUIDE.md`
- `reports/daily_workflow_sample.md`

## 6. 2025 数据与测试方案

当前已提供 2025 数据搬运和多题测试的方案文件，但默认不包含 2025 全量数据库：

- `DATA_MIGRATION_2025_PLAN.md`
- `TEST_PLAN_2025_DETAILED.md`
- `TEST_CASE_TEMPLATE_2025.md`
- `SCORING_STANDARD_2025.md`
- `FUTURE_LEAKAGE_GUARD_2025.md`

真正搬运数据前，需要用户确认 Tushare 权限、数据库路径、概念板块历史成分处理方式，以及是否接受第一版先用申万行业和人工观察池。

## 7. 如何让 Codex 接手

对 Codex 说：

```text
请先读取 skills/stock_strategy_lab/SKILL.md 和 PROJECT_STATUS.md，然后按其中规则继续开发，不要自动交易，不要调权重，不要使用未来数据。
```

## 8. 常见问题

- 缺少依赖：运行 `pip install -r requirements.txt`。
- Tushare token未配置：复制 `.env.example` 为 `.env` 并填写。
- 数据库不存在：把数据库放到 `data/sqlite/market_120d.sqlite` 或重新拉取。
- 中文乱码：PowerShell 输出乱码不一定代表文件坏，用 UTF-8 编辑器查看。
- 路径错误：确认命令在项目根目录执行。
- 报告生成失败：先运行 `python scripts/health_check.py`。
- Codex找不到skill：确认 `skills/stock_strategy_lab/SKILL.md` 存在，并让 Codex 先读取它。

## 2025 基础数据 MVP 位置

当前已执行 2025 基础数据 MVP，数据库默认不放在项目 C 盘目录，而是放在：

```text
D:/股票AI交易助手数据/sqlite/market_2025.sqlite
```

常用检查命令：

```powershell
python scripts/check_2025_data_integrity.py --db-path "D:/股票AI交易助手数据/sqlite/market_2025.sqlite"
python scripts/inspect_2025_database.py --db-path "D:/股票AI交易助手数据/sqlite/market_2025.sqlite"
```
