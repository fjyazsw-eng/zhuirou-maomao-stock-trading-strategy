
## 股票数据源强制入口

先读取仓库根目录 `DATA_SOURCES.md`。所有 A 股取数强制 hithink-finance -> mootdx（仅分钟线），无 Tushare 或其他自动回退。旧报告/备份不是现行取数规则。
# 赘肉猫猫的股票交易策略

股票AI交易助手是一个本地运行的 A 股研究辅助项目，包含结构化分析和只读实时盯盘。它按市场、板块、核心股、个股、资金与成交、仓位和风险的顺序组织证据，并把事实、推断和触发条件分开。

## 已实现功能

- 空仓咨询、持仓咨询、板块与候选分析。
- 日报、层级报告和持仓风险提示。
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，mootdx 仅分钟线，失败报错。
- 用户确认方案后的只读盯盘与可选消息通知。
- 无 Token、无数据库时可运行的固定脱敏离线 Demo。
- 健康检查、自动测试、发布验收和跨平台 ZIP 清单。

## 不包含什么

- 不连接券商真实账户，不自动交易，不真实下单。
- 不承诺收益，不把推断写成事实，不使用未来数据。
- 发布包不包含真实密钥、数据库、个人持仓、历史报告或 CC Connect 会话。

## 五分钟快速开始

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/bootstrap_project.py
.\.venv\Scripts\python.exe scripts/health_check.py
.\.venv\Scripts\python.exe scripts/run_demo.py
.\.venv\Scripts\python.exe -m pytest -q
```

Linux 和 macOS 将 Python 路径替换为 `.venv/bin/python`。

## 四个主要入口

- 空仓/持仓咨询：按照 [股票分析工程文件](股票分析工程文件.md) 的统一口径执行。
- 日报：`python scripts/run_daily_workflow.py`。
- 实时盯盘：参见 [REALTIME_WATCH_MONITOR.md](REALTIME_WATCH_MONITOR.md)。
- 离线验证：`python scripts/run_demo.py`。

## 数据源与配置

复制 `.env.example` 为 `.env`，按需填写自己的凭据。默认数据库是 `data/sqlite/market_120d.sqlite`，外部数据库通过 `STOCK_AI_MARKET_DB` 和 `STOCK_AI_WALK_FORWARD_DB` 指定。缺少配置时必须明确降级，不得伪造数据。

> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，mootdx 仅分钟线，失败报错。

## 目录

- `scoring_system/`：冻结的核心分析模块。
- `scripts/`：初始化、健康检查、工作流和发布工具。
- `skills/stock_strategy_lab/`：项目协作 Skill。
- `examples/`：固定脱敏 Demo。
- `docs/`：设计、路线图和交易决策框架。
- `config/`：非私密配置模板。

## 测试与发布检查

```powershell
python -m pytest -q
python scripts/release_check.py
```

发布检查只有在必要文件、编译、测试、Demo、路径、秘密扫描和 manifest 全部通过时才输出 `RELEASE_READY`。

## Skill

其他 Codex 用户可以把 `skills/stock_strategy_lab` 复制到自己的技能目录。Skill 规定输入输出、数据降级、风险边界和四类工作入口。

## 风险声明

本项目只用于研究辅助和复盘。所有实际交易决定由用户自行作出并承担风险。
