
## 股票数据源强制入口

先读取仓库根目录 `DATA_SOURCES.md`。所有 A 股取数强制 hithink-finance -> mootdx（仅分钟线），无 Tushare 或其他自动回退。旧报告/备份不是现行取数规则。
# 股票AI交易助手安装与恢复

支持 Python `>=3.11,<3.14`，Windows、Linux 和 macOS 均可使用。以下命令以 Windows PowerShell 为例。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/bootstrap_project.py
```

`bootstrap_project.py` 会创建必要目录，并在 `.env` 不存在时从占位模板生成，不写入真实密钥。

## 首次自检

```powershell
.\.venv\Scripts\python.exe scripts/health_check.py
.\.venv\Scripts\python.exe scripts/run_demo.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/release_check.py
```

未配置 Token、数据库和消息渠道时，健康检查应为 `PASS_WITH_WARNINGS`；离线 Demo 和测试仍应成功。

## 数据

- 默认数据库：`data/sqlite/market_120d.sqlite`。
- 外部市场数据库：设置 `STOCK_AI_MARKET_DB`。
- Walk-forward 数据库：设置 `STOCK_AI_WALK_FORWARD_DB`。
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，mootdx 仅分钟线，失败报错。
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，mootdx 仅分钟线，失败报错。

## 消息渠道

飞书、企业微信、Telegram 和 CC Connect 均为可选能力。发布包不包含凭据或个人会话；目标电脑需要单独配置。

## Skill 安装

将 `skills/stock_strategy_lab` 复制到目标 Codex 的技能目录，重新启动 Codex。使用前先运行健康检查；没有真实数据时只能运行 Demo，不得把 Demo 当实时行情。

## 日常流程

```powershell
.\.venv\Scripts\python.exe scripts/run_daily_workflow.py
```

缺少 score 或 decision 前置文件时，相关阶段会标记 `SKIPPED`，整体返回 `PARTIAL` 或 `BLOCKED`，不会报告不存在的成功产物。
