
## 股票数据源强制入口

先读取仓库根目录 `DATA_SOURCES.md`。所有 A 股取数强制 hithink-finance -> akshare-sina-minute（仅分钟线），无 Tushare 或其他自动回退。旧报告/备份不是现行取数规则。
# 股票AI交易助手工作流快速启动

这份文档给第一次接触项目的人或新 Codex 使用。

## 1. 项目是做什么的

股票AI交易助手是本地 A 股研究和复盘辅助工具。它帮助整理市场、板块、候选、盘中否决、持仓复盘和周度复盘。

它不是自动交易系统，不连接券商账户，不真实下单。

## 2. 环境要求

- Python `>=3.11,<3.14`
- Windows PowerShell、Linux shell 或 macOS shell
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，AKShare 新浪分钟线仅分钟线，失败报错。
- 可选：本地行情数据库
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，AKShare 新浪分钟线仅分钟线，失败报错。

Windows 推荐统一使用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 ...
```

## 3. 第一次安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Linux/macOS 将 Python 路径换成 `.venv/bin/python`。

## 4. Token 如何配置

复制 `.env.example` 为 `.env`，填写自己的 Token。

```text
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，AKShare 新浪分钟线仅分钟线，失败报错。
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，AKShare 新浪分钟线仅分钟线，失败报错。
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，AKShare 新浪分钟线仅分钟线，失败报错。
```

不要把 `.env` 提交到 GitHub。检查输出只显示是否存在和掩码，不显示完整 Token。

## 5. 如何运行环境检查

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py setup
```

结果只有三类：

- `READY`
- `READY_WITH_WARNINGS`
- `NOT_READY`

## 6. 如何查看当前阶段

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py status
```

这是只读命令，不修改状态。

## 7. 如何运行下一步

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py next
```

`next` 只判断下一步，不跳过必要阶段。

## 8. 每周末怎么开始

先运行状态检查，确认当前阶段是 `WEEKEND_REALITY_PENDING`。

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py status
```

周末现实分析必须先完成，之后才能进入人工六爻输入。

## 9. 每天晚上怎么生成计划

当前阶段到达前夜计划时使用：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py night-plan --input-json plan.json
```

如果系统性风险总闸开启，首选和替补会挂起，不会生成可执行买入。

## 10. 盘中怎么运行否决

盘中只检查前夜首选和替补：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py intraday-check --input-json intraday_check.json
```

盘中不得重新生成第三只股票。

## 11. 收盘怎么复盘

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py closing-review --input-json closing_review.json --trade-date 20260720
```

收盘复盘记录市场、板块、候选、执行、否决和下一交易日关注点。

## 12. 周五怎么完成周报

周五收盘复盘后运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py weekly-review
```

完成后下一周重新从周末现实分析开始。

## 13. 常见错误

- `NOT_READY`：先看 `failed_checks` 和 `recommended_actions`。
- 缺 Token：复制 `.env.example` 为 `.env` 并填写自己的 Token。
- 网络失败：可先用离线状态和测试检查，不得把旧数据说成当前数据。
- 工作流状态损坏：用 `reports/workflow/current_workflow_state.example.json` 重新生成初始状态。
- 中文乱码：PowerShell 读取中文文件用 `-Encoding UTF8`。

## 14. 如何迁移到新电脑

复制代码、示例配置、必要报告和 workflow state。不要复制 `.env` 给别人，不要上传真实状态。

详细见 `docs/MIGRATION_GUIDE.md`。

## 15. 如何从 GitHub 恢复

```powershell
git clone <repo-url>
cd <repo>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
copy .env.example .env
```

再运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py setup
```

## 16. 如何验证是否安装成功

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts/run_project.py validate
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 -m pytest -q
```

## 新 Codex 第一次接手固定指令

```text
请先读取 PROJECT_CONTEXT.md、WORKFLOW_QUICKSTART.md 和 skills/stock-ai-workflow-controller/SKILL.md。运行环境检查，读取当前工作流状态，只告诉我当前阶段、缺失条件和下一步。不要修改评分、策略、阈值或状态，除非我明确要求。
```

## 三个常用口令

```text
执行当前工作流下一步。
```

```text
查看当前工作流状态，不修改任何内容。
```

```text
运行今天的盘中否决，只检查前夜首选和替补。
```


