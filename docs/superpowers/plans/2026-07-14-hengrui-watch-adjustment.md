# 恒瑞医药盯盘策略调整 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把恒瑞医药的观察区小幅上移到更贴近现价的区间，并保留只提醒关键动作的平衡观察策略。

**Architecture:** 只调整盯盘配置，不改实时盯盘状态机代码。同步更新项目文档，并用一次本地监控运行验证配置可被正常读取和执行。

**Tech Stack:** JSON 配置、Markdown 文档、Python 监控脚本

## Global Constraints

- 不接真实账户。
- 不自动交易。
- 不真实下单。
- 对用户实际输出保持大白话。
- 不处理 Git，除非用户明确要求。
- 本次只调整恒瑞医药盯盘配置，不修改其他股票。

---

### Task 1: 更新恒瑞医药平衡观察配置并验证

**Files:**
- Modify: `config/realtime_watchlist.json`
- Modify: `REALTIME_WATCH_MONITOR.md`
- Create: `docs/superpowers/specs/2026-07-14-hengrui-watch-design.md`
- Create: `docs/superpowers/plans/2026-07-14-hengrui-watch-adjustment.md`

**Interfaces:**
- Consumes: `scripts/run_realtime_watch_monitor.py --once`
- Produces: 恒瑞医药新区间 `55.00` 到 `56.00`，维持候选股只通知 `CONFIRMED` 和 `INVALIDATED`

- [ ] **Step 1: 更新配置**

把恒瑞医药观察区从 `54.50-55.50` 调整为 `55.00-56.00`，其余候选股和通知规则不变。

- [ ] **Step 2: 更新文档**

把实时盯盘说明中的恒瑞医药观察区同步改成 `55.00 至 56.00`，并补充这次设计留档。

- [ ] **Step 3: 本地运行一次监控**

Run: `.\.venv\Scripts\python.exe scripts\run_realtime_watch_monitor.py --once`

Expected:
- 命令成功返回
- 配置加载正常
- 输出里能看到恒瑞医药监控结果

- [ ] **Step 4: 检查最新诊断文件**

Run: `Get-Content reports/realtime_watch/latest_monitor_status.json -Encoding UTF8`

Expected:
- 文件已更新
- 恒瑞医药条目存在
- 没有因为配置错误导致脚本崩溃
