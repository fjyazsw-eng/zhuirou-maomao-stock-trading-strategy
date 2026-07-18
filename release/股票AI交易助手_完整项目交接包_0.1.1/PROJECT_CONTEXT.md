# 股票AI交易助手项目上下文

最后整理日期：2026-07-10

这份文件用于在 API 模式或新对话中延续项目背景。它不是历史聊天记录的恢复文件，而是从项目现有 README、状态说明、交接文档和流程文档整理出的当前工作上下文。

## 先说清楚：API 模式不能直接继承账户模式聊天

API 模式不会自动读取 ChatGPT/Codex 账户模式里的历史聊天记录，也不会天然继承账户模式侧边栏中的旧对话上下文。只有已经落到本地项目文件、会话导出文件、交接文档、README、summary、memory 等可读文件里的内容，才能稳定作为上下文继续使用。

因此本项目采用替代方案：把关键历史背景沉淀到本文件。以后新对话或 API 模式启动时，先读取本文件，再按下面的入口文件补充最新状态。

## 项目定位

项目名称：股票AI交易助手。

这是一个本地股票交易学习、研究辅助和实战复盘项目。它帮助整理市场信息、形成结构化观察、生成日报和复盘材料，并逐步接入行情数据、本地数据库和自动化报告。

项目边界：

- 不接真实交易账户。
- 不自动交易。
- 不真实下单。
- 不替代人工决策。
- 不承诺收益。
- 不把分析结果写成确定性买卖建议。

## 当前核心口径

对用户输出统一叫“股票AI交易助手”，不要让用户理解成多个内部模型在互相冲突。

内部可保留两条线：

- 市场与选股：市场天气、阶段主线、潜在主线、情绪热点、退潮方向、候选股。
- 持仓与交易判断：候选股是否能模拟买入、是否只能观察、是否需要人工确认、持仓是否 HOLD / REDUCE / SELL。

最终回答要把两条线合并成人能读懂的一句话：先讲市场和板块，再讲个股动作。

新增统一分析咨询工程文件：

- 对外对话、飞书、微信、企业微信、其他智能体统一优先遵循 `股票分析工程文件.md`
- 原则是“内部复杂判断，外部简洁输出”
- 默认只输出结论、动作、仓位、条件，不展开完整推导
- 默认结论尽量明确，不轻易只给“观望”
- 若数据异常，优先反馈是否为 Tushare 问题

## 硬边界

长期保持：

- 不处理 Git，除非用户明确要求。
- 不进入 `FULL_PIPELINE_SELECTION_WALK_FORWARD`。
- 不接真实账户。
- 不自动交易。
- 不真实下单。
- 不接消息面模块。
- 不修改评分权重。
- 不改变历史 Walk-forward 结果。
- 不改变历史收益计算。
- 不做全市场自动选股，除非用户明确要求并重新确认范围。
- `validation_private` 不能用于当天决策。
- 行情缺失时不能编造价格。
- 飞书只做通知，不代表买卖执行。
- 用户实际持仓只做盯盘和咨询，不接入真实交易。

## 当前账户状态

正式模拟账户文件：

`reports/simulated_live_v1/state/simulated_account_state.json`

已知状态来自 2026-07-07 交接文档：

- 初始资金：20000
- 现金：20000
- 总权益：20000
- 持仓：空
- 单票上限：100%
- 总仓位上限：100%
- 每日新增买入最多：1
- 每日总交易最多：2
- 一手：100 股
- `real_account_connected=false`
- `auto_trading_enabled=false`
- `news_module_enabled=false`

说明：单票 20% 和总仓位 60% 的旧限制已取消；当前只影响模拟账户，不代表真实账户授权。

## 当前 Tushare 接入口径

- 统一客户端：`scoring_system/tushare_client.py`
- 当前优先配置：若 `.env` 存在 `TUSHARE_REPLAY_API_KEY`，优先走 replay API
- 回退逻辑：若未配置 replay key，则继续走 `TUSHARE_TOKEN` / `TUSHARE_TOKEN_PRO`
- 适用要求：后续所有 Codex 对话、API 模式和脚本接入，优先复用这个统一客户端，不再各脚本散写不同接法
- 行业成分当前主接口：申万行业成分使用 `index_member_all`，中信行业成分使用 `ci_index_member`
- 旧 `index_member` 当前不作为在线主接口；本地 SQLite/CSV 中仍可保留 `index_member` 表名作为兼容缓存结构
- 行业成分用于补强板块归属、扩散度、龙头/后排和盯盘环境判断，不自动改变已冻结的评分权重、买卖标签或仓位规则
- 公司基本面当前可用：`stock_company`、`income`、`balancesheet`、`cashflow`、`fina_indicator`；只用于轻量排雷、主营匹配和财务质量检查
- 当前不依赖 Tushare 做新闻公告和实时价：`anns_d`、`major_news`、`news`、`realtime_quote`、`stk_mins` 当前权限或通道不足；盘中实时盯盘继续用东方财富只读分时补充
- 统一适用范围：本地对话、API 模式、飞书、微信/企业微信、CC Connect 消息

## 当前主模拟标的

主标的：

- 恒瑞医药 `600276.SH`

最近交接结论：

- 最新已验证行情日：`20260706`
- 收盘价：`56.77`
- 涨跌幅：`+4.2608%`
- 数据源：`tushare_readonly`
- `buy_point_quality=FAIR`
- `simulated_buy_point_triggered=true`
- `manual_confirmation_required=true`
- `auto_trade_executed=false`
- `real_order_placed=false`

注意：这些是交接时点信息。继续执行前必须读取最新账户状态和最新行情，不要把旧价格当作当前价格。

## 当前候选与观察范围

正式模拟优先级：

1. 恒瑞医药 `600276.SH`：主模拟标的，可在人工确认和行情满足时小仓试错。
2. 百济神州 `688235.SH`：医药核心观察，不自动买入。
3. 荣昌生物 `688331.SH`：生物医药观察，重点看回落后承接。
4. 益生股份 `002458.SZ`：养殖业潜在主线观察，不从 WATCH 直接变 BUY。
5. 万邦医药 `301520.SZ`：人工映射观察样本，不能视为正式板块成分验证结果。

`WATCH` / `WATCH_ONLY` 只能解释为观察，不能解释成买入。`BUY_CANDIDATE` 只能解释为人工确认级别的小仓试错候选，不能解释成自动买入。

## 用户实际持仓盯盘

用户实际持仓只做盯盘，不纳入完整交易执行链：

- 行云科技 `300209.SZ`
- 建业股份 `603948.SH`
- 万润股份 `002643.SZ`
- 广钢气体 `688548.SH`
- 格科微 `688728.SH`
- 有研硅 `688432.SH`

用户曾写“科格微”，工程核对后按“格科微 688728.SH”处理。

盯盘口径：

- 可以分析走势、承接、风险、板块影响。
- 可以在日报中提醒强弱变化。
- 不写成真实账户买卖指令。
- 不接真实账户。
- 不自动交易。

## 当前工程状态

来自 `PROJECT_STATUS.md`：

- 数据纪律/封闭测试：MVP 可用。
- 板块周期模块：MVP 通过，已接入日报。
- 执行标签与仓位模块：MVP 通过，已冻结。
- 持仓管理与利润保护：MVP 通过，已冻结。
- 龙头/补涨/后排识别：MVP 通过，已冻结。
- 日常报告/HTML 看板：已接入核心字段。
- 账户级仓位管理：MVP 通过，已接入日报和账户报告。
- 日常运行流程固化：MVP 通过。
- 盘中提醒/飞书/TG：后续计划。
- 2025 历史数据：已做基础搬运 MVP，但仍有警告项。

冻结边界：当前核心 MVP 模块已阶段性冻结。除非用户明确要求，不继续调标签、阈值和评分权重。

## 日常工作流

入口文件：

- `DAILY_WORKFLOW.md`
- `REPORT_READING_GUIDE.md`
- `股票分析工程文件.md`

固定阅读顺序：

1. 大盘天气。
2. 优势板块。
3. 板块周期。
4. 个股角色。
5. 执行标签。
6. 仓位建议。
7. 持仓管理。
8. 账户风险。

核心原则：

- 风险控制优先于个股分数。
- 风险环境下不为了买而买。
- 高分股票不等于可以买。
- 板块高潮不追高。
- 板块分歧先等承接。
- 不能盯盘时自动更保守。

## 数据与买点闸门

所有买点判断必须包含：

- `quote_data_source`
- `quote_trade_date`
- `latest_quote_loaded`
- `buy_point_data_ready`
- `buy_point_judgement_source`

如果行情缺失，必须写：

“行情数据不足，暂不判断买点。”

如果 `buy_point_data_ready=false`，不允许输出 `simulated_buy_point_triggered=true`。

## 飞书与自动化

已创建过 Codex 自动化：

- `ai-2`：交易日 12:00，模拟操作中午反馈。
- `ai-3`：交易日 15:30，模拟操作收盘反馈。

注意：这些是 Codex 本机自动化，不是飞书云端定时器。通常需要电脑开机、网络可用、Codex 自动化运行环境可用、飞书 webhook 配置有效。若 Codex 应用完全关闭或电脑休眠，任务可能不会按时执行。

发送脚本：

`scripts/send_feishu_utf8.py`

发送前必须自查 UTF-8，避免乱码。

新增只读实时盯盘：

- 工程说明：`REALTIME_WATCH_MONITOR.md`
- 配置：`config/realtime_watchlist.json`
- 入口：`scripts/run_realtime_watch_monitor.py`
- 数据：东方财富一分钟分时、盘中资金流、板块分时和参照股；历史成交基准走统一 Tushare 客户端
- 消息：通过 CC Connect 项目 `codex-weixin` 投递到活跃微信和飞书会话
- 当前监控：恒瑞医药、药明康德、中国船舶及对应板块
- 当前持仓保护监控：华工科技 300股、成本162；光迅科技100股、成本176
- 持仓计划必须先拟定、经用户明确确认后再更新盯盘配置；微信/飞书确认的新版方案同样适用
- 边界：只读、只提醒、不接账户、不自动交易、不真实下单

## 关键脚本

- `scripts/fetch_simulated_live_v1_market_data_readonly.py`
- `scripts/fetch_handoff_latest_readonly_quotes.py`
- `scripts/build_simulated_live_v1_daily_report.py`
- `scripts/build_unified_stock_ai_daily_report.py`
- `scripts/run_simulated_live_v1_trading_model_handoff_test.py`
- `scripts/update_simulated_account_state.py`
- `scripts/send_feishu_utf8.py`
- `scripts/check_simulated_live_v1_readonly_flow_regression.py`

## 关键上下文入口

启动新对话或 API 模式时，建议按顺序读取：

1. `PROJECT_CONTEXT.md`
2. `reports/simulated_live_v1/review/complete_handoff_for_new_chat_20260707.md`
3. `reports/simulated_live_v1/state/simulated_account_state.json`
4. `reports/simulated_live_v1/review/trading_model_handoff_retest_20260706.json`
5. `PROJECT_STATUS.md`
6. `DAILY_WORKFLOW.md`
7. `REPORT_READING_GUIDE.md`
8. `股票分析工程文件.md`

如果只需要快速接上项目，至少读取第 1-4 项。

## 新对话启动提示词

可以直接这样说：

```text
请先读取 PROJECT_CONTEXT.md，然后按里面的“关键上下文入口”继续读取项目状态。之后所有回答都按股票AI交易助手当前口径执行：不接真实账户、不自动交易、不编造行情、用户实际持仓只盯盘；最终分析咨询表达遵循 股票分析工程文件.md。
```

## 后续维护规则

当项目状态发生明显变化时，更新本文件：

- 模拟账户资金、持仓、风控上限变化。
- 主模拟标的变化。
- 用户实际持仓列表变化。
- 自动化任务变化。
- 关键脚本或关键报告入口变化。
- 硬边界变化。

不要把临时闲聊全文塞进本文件，只沉淀会影响后续工作的事实、决策、边界和入口。
