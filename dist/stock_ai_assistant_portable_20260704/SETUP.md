# 股票AI交易助手部署说明

本说明用于在新电脑或新 Codex 环境恢复“股票AI交易助手”的开发和运行环境。

## 1. 新电脑准备条件

- Windows 10/11。
- Python 3.11 或 3.12，建议使用64位版本。
- PowerShell。
- 可访问 Tushare、飞书或 Telegram 的网络环境按需配置。
- Codex 登录状态需要在新电脑重新完成。

## 2. 创建虚拟环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 禁止执行脚本，可以先运行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 3. 安装依赖

```powershell
pip install -r requirements.txt
```

## 4. 配置 Tushare token

复制 `.env.example` 为 `.env`，填入自己的 token。不要把 `.env` 发给别人，不要打包真实 token。

```powershell
copy .env.example .env
```

## 5. 放置本地数据库

默认数据库位置：

```text
data/sqlite/market_120d.sqlite
```

如果没有数据库，先运行健康检查，按提示重新拉取或重建数据。

## 6. 运行健康检查

```powershell
python scripts/health_check.py
```

如果输出 `PASS_WITH_WARNINGS`，通常说明能运行，但缺少数据库或 token 等可选配置。

## 7. 生成最新日报

优先使用现有生成器：

```powershell
python scoring_system/hierarchy_report.py
```

如果失败，先运行：

```powershell
python scripts/health_check.py
```

## 8. 打开 HTML 看板

生成后打开：

```text
reports/latest_market_decision_dashboard.html
```

也可以双击：

```text
open_latest_dashboard.bat
```

## 9. 常见错误

- 缺少依赖：重新运行 `pip install -r requirements.txt`。
- Tushare token 未配置：检查 `.env` 或系统环境变量。
- 数据库不存在：检查 `data/sqlite/market_120d.sqlite`。
- 中文乱码：PowerShell 显示乱码不一定代表文件损坏，优先用 UTF-8 编辑器查看。
- 路径错误：确认当前目录是项目根目录。
- 报告生成失败：先运行 `python scripts/health_check.py`。

## 10. 让 Codex 接手

对 Codex 说：

```text
请先读取 skills/stock_strategy_lab/SKILL.md 和 PROJECT_STATUS.md，然后按其中规则继续开发。不要自动交易，不要调权重，不要使用未来数据。
```

## 11. 安全边界

本项目不自动交易、不接券商真实账户、不保证盈利。所有输出都是辅助判断，最终决策由用户自己负责。
