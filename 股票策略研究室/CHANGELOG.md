# 项目变更记录

## 2026-06-29

- 建立第一版长期研究系统文档。
- 完善角色分工、最高原则、固定分析框架和风险边界。
- 新增账户基准配置文件。
- 新增股票观察池配置文件。
- 新增日报、周报、持仓、换仓、六爻现实校准和复盘模板。
- 新增数据来源登记文件。
- 保留早期目录，不删除历史结构。

## 2026-06-29 账户基准结构修复

- 为 `config/account_baseline.yaml` 中的 5 只持仓补充 `code`、`exchange`、`symbol`、`asset_type`、`status` 字段。
- 为 `config/watchlist.yaml` 中的 2 只观察股票补充 `code`、`exchange`、`symbol`、`asset_type` 字段，并将 `status` 统一为 `watch`。
- 保持账户金额、持股数量、持仓成本、仓位和账户约束不变。
- 明确股票代码以字符串保存，避免前导零丢失。

## 2026-06-29 日常数据任务建设

- 将 `10:30 盘中盯盘监控` 自动化从一次性任务调整为工作日每日 10:30 重复任务。
- 新增 `docs/daily_task_specs.md`，定义晨报、10:30 盘中盯盘、收盘复盘三类任务的边界、输入和输出结构。
- 新增 `scripts/fetch_market_snapshot.py`，用于抓取公开行情、板块、市场宽度和公告快照。
- 脚本不连接券商账户，不执行交易，不生成买卖建议。

## 2026-06-30 Tushare 接入测试

- 新增 `scripts/test_tushare_connection.py`，用于最小化验证 Tushare SDK、`TUSHARE_TOKEN` 环境变量和交易日历接口。
- 脚本只读取本机环境变量，不保存密钥，不连接券商账户，不执行交易，不生成交易建议。
- 首次实测已确认 Python、Tushare SDK 和 Token 可读取；交易日历接口后续触发 Tushare 频率限制时会输出 `PARTIAL PASS`。

## 2026-06-30 Tushare amount 单位修正

- 明确 Tushare `daily.amount` 单位为千元。
- 新增 `scripts/amount_units.py`，统一提供 `amount` 从千元到亿元、万亿元的换算函数。
- 新增 `tests/test_amount_units.py`，验证 `amount=100000` 时换算结果为 `1` 亿元。
- 未改动 `vol` 成交量单位。

## 2026-06-30 最近5个交易日市场天气模块

- 新增 `scripts/market_weather_5d.py`，按最近5个有效交易日计算市场宽度、成交额趋势、强弱结构和天气评分。
- 新增 `tests/test_market_weather_5d.py`，覆盖字段校验、重复识别、空数据、本地缓存优先、非交易日不计入有效交易日等场景。
- 复用 `scripts/amount_units.py` 进行 Tushare `daily.amount` 千元到亿元、万亿元换算，未改动 `vol` 单位。
- 生成 `data/processed/market_weather_5d_20260630.csv` 和 `reports/market_weather_5d_20260630.md`。

## 2026-06-30 第二阶段基础数据整合

- 新增 `scripts/build_daily_stock_master.py`，基于本地缓存整合 `daily`、`stock_basic`、`daily_basic`，生成每日股票基础总表。
- 新增 `tests/test_daily_stock_master.py`，覆盖 `symbol` 前导零修复、左连接保留行、PE/PB 缺失不删行、指数名册未覆盖不猜代码等场景。
- 生成 `data/processed/daily_stock_master_20260630.csv` 和 `reports/daily_stock_master_quality_20260630.md`。
- 本阶段只使用现有缓存，未调用新接口，未读取或打印完整 Token。

## 2026-06-30 主要指数天气表

- 新增 `scripts/build_major_index_weather.py`，整理7个主要指数最近20个有效交易日数据并生成指数风格证据表。
- 新增 `tests/test_major_index_weather.py`，覆盖指数代码不猜测、收益计算、本地缓存优先和风格判断逻辑。
- 生成 `data/processed/major_index_weather_20260630.csv` 和 `reports/major_index_weather_20260630.md`。
- 本阶段不修改既有天气评分，只提供指数证据；未打印或修改 Token。

## 2026-06-30 行业街区地图

- 新增 `scripts/build_industry_map.py`，基于申万 `SW2021` 行业分类和行业成分缓存构建行业街区地图。
- 新增 `tests/test_industry_map.py`，覆盖行业匹配、不强行分类、行业统计、连续走强/单日反弹/转弱分类等逻辑。
- 生成 `data/processed/industry_map_20260630.csv`、`stock_industry_matched_20260630.csv`、`stock_industry_unmatched_20260630.csv` 和 `reports/industry_map_20260630.md`。
- 本阶段不修改天气评分，不打印或修改 Token，不接入资金流、龙虎榜、财务报表或新闻接口。

## 2026-06-30 行业分析正式升级

- 新增 `scripts/build_industry_deep_analysis.py`，使用申万 SW2021 一级/二级行业分类，拆分电子等宽行业。
- 加入行业成交额相对昨日、5日均值和全市场占比变化。
- 接入并缓存最近5个交易日 Tushare 个股资金流 `moneyflow`，汇总到一级/二级行业。
- 输出强势行业、持续走强、单日反弹、转弱行业和班长候选报告。
- 资金流只作为辅助证据，不作为单独交易依据；未打印或修改 Token。
