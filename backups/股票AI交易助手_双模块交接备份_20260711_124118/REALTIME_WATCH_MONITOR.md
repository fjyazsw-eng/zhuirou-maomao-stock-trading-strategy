# 股票AI交易助手实时盯盘

## 定位

该模块只做只读行情监控、条件判断和消息提醒：

- 不接真实账户。
- 不自动交易。
- 不真实下单。
- 不把盘中资金流单独当作买入依据。

## 当前观察范围

| 股票 | 代码 | 观察区间 | 板块 |
|---|---|---:|---|
| 恒瑞医药 | 600276.SH | 54.50 至 55.50 | 化学制药 |
| 药明康德 | 603259.SH | 119.00 至 122.00 | 医疗服务 |
| 中国船舶 | 600150.SH | 36.30 至 36.90 | 船舶制造 |

当前持仓保护范围：

| 股票 | 代码 | 持仓 | 成本 | 保护位 | 风险线 | 修复位 | 转强位 |
|---|---|---:|---:|---:|---:|---:|---:|
| 华工科技 | 000988.SZ | 300股 | 162.00 | 157.80 | 153.50 | 161.30 | 165.00 |
| 光迅科技 | 002281.SZ | 100股 | 176.00 | 233.00 | 229.00 | 238.50 | 245.00 |

配置文件：`config/realtime_watchlist.json`。

## 判断顺序

```text
实时价格 -> 两个完整5分钟周期 -> 同期成交强度 -> 盘中资金变化 -> 大盘 -> 板块与参照股 -> 状态变化提醒
```

状态包括：

- `ZONE_REACHED`：价格进入观察区，尚未站稳。
- `HOLDING`：价格出现承接，但量能、资金或板块尚未全部确认。
- `CONFIRMED`：价格、量能、资金和板块综合站稳。
- `TURNING_STRONG`：综合站稳后继续转强。
- `INVALIDATED`：跌破观察区下沿且超出容差。
- `DATA_STALE`：行情日期不是今天，不做盘中判断。
- `DATA_ERROR`：数据异常，不编造结论。

东方财富分钟接口若没有提供足够的同分钟历史，系统使用 Tushare 前5日完整成交额和当前交易时段进度计算估算值，并在机器报告中标记 `tushare_5d_elapsed_projection`。

## 运行

单次诊断，不发送消息：

```powershell
.\.venv\Scripts\python.exe scripts\run_realtime_watch_monitor.py --once
```

持续运行并通过 CC Connect 发送状态变化：

```powershell
.\.venv\Scripts\python.exe scripts\run_realtime_watch_monitor.py --send
```

安装当前用户开机启动并立即启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_realtime_watch_monitor.ps1 -StartNow
```

最新诊断：`reports/realtime_watch/latest_monitor_status.json`。

## 消息通道

消息通过 CC Connect `send` 命令投递到项目 `codex-weixin` 当前活跃的微信和飞书会话。监控轮询不会每次调用 Codex，只有状态改变时发送消息，因此不会产生持续的大量模型 Token 消耗。

微信或飞书某一端临时投递失败时，系统只重试失败平台；去重状态按交易日保存，不会吞掉下一交易日的同名状态提醒。

## 方案调整流程

用户可在微信、飞书或本地对话提供最新持仓和计划。股票AI交易助手先拟定新版保护位、风险线、修复位和转强位；只有用户明确确认后，才更新 `config/realtime_watchlist.json`。后台从下一轮开始读取并执行最新确认方案，旧方案不再作为提醒依据。

配置支持热加载，不需要手动重启后台进程；文件更新后下一轮轮询自动生效。
