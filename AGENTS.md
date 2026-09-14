
## 股票数据源强制入口

先读取仓库根目录 `DATA_SOURCES.md`。所有 A 股取数强制 hithink-finance -> akshare-sina-minute（仅分钟线），无 Tushare 或其他自动回退。旧报告/备份不是现行取数规则。
# Codex Project Instructions

启动本仓库的新对话或 API 模式任务时，先读取 `PROJECT_CONTEXT.md`，再按其中“关键上下文入口”读取必要文件。

运行与读取规范：

- 在 PowerShell 中读取中文文件必须显式使用 `-Encoding UTF8`。
- 不要直接输出全仓库 `rg --files` 的完整结果；需要找文件时先限定目录、文件名或用 `Select-Object -First` 控制输出量。
- 如果默认 `python` 指向 WindowsApps 占位程序或无输出失败，先运行 `scripts/check_codex_runtime_health.ps1`，再使用脚本提示的可用 Python。
- 本仓库运行 Python 脚本优先用 `powershell -ExecutionPolicy Bypass -File scripts/run_project_python.ps1 ...`，避免误用 WindowsApps 占位程序。
> 数据源规则已替换：统一遵循仓库根目录 DATA_SOURCES.md；hithink-finance 主源，AKShare 新浪分钟线仅分钟线，失败报错。
- 读取行情 JSON 时优先抽取摘要字段，不直接整段输出 `history_daily_raw` 等长历史数组。
- 只为回答当前问题读取必要入口文件，避免一次性展开无关报告、缓存和测试样例。

长期遵守：

- 不接真实交易账户。
- 不自动交易。
- 不真实下单。
- 不编造行情、价格或数据。
- 用户实际持仓只做盯盘和咨询，不写成真实账户买卖指令。
- 当前核心 MVP 模块已冻结；除非用户明确要求，不调整标签、阈值或评分权重。
- 对用户统一使用“股票AI交易助手”口径，不拆成多个内部模型解释。

如果上下文文件与用户最新明确指令冲突，先指出冲突，再按用户最新指令处理。


