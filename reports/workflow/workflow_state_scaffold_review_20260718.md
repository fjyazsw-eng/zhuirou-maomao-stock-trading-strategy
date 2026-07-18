# 工作流状态骨架搭建审查 20260718

本轮目标：建立一个只保存状态的连续衔接文件，让周末现实分析、六爻人工校准、前夜计划、盘中否决、日内执行、收盘复盘和周五复盘后续可以共用同一个状态入口。

本轮边界：未修改市场评分、板块评分、A/B/C 策略、100 股规则、盘中监控函数、持仓规则；未新增系统性风险算法；未新增六爻评分算法；未自动调用东方财富、Tushare、交易或下单接口。

## 1. 新增或修改文件

新增：

| 文件 | 用途 |
|---|---|
| `scoring_system/workflow_state.py` | 工作流状态创建、读取、指定部分更新、阶段转换校验、JSON 结构校验、Markdown 生成 |
| `scripts/run_workflow_state_tool.py` | 命令行薄入口：create/read/validate/render/update-section |
| `tests/test_workflow_state_scaffold.py` | 最小单元测试，覆盖创建、写入各阶段、非法阶段、Markdown 生成 |
| `reports/workflow/current_workflow_state.json` | 当前工作流状态 JSON，初始空白骨架 |
| `reports/workflow/current_workflow_state.md` | 当前工作流状态人类可读版本 |
| `reports/workflow/workflow_state_scaffold_review_20260718.md` | 本轮搭建审查报告 |

修改：

| 文件 | 用途 |
|---|---|
| 无既有策略文件修改 | 本轮只新增状态骨架相关文件 |

## 2. 状态结构示例

当前状态文件：

`reports/workflow/current_workflow_state.json`

关键结构：

```json
{
  "workflow_version": "workflow_state_v1",
  "latest_completed_trade_date": "20260717",
  "current_stage": "WEEKEND_REALITY_PENDING",
  "weekend_reality_analysis": {
    "market_state": "",
    "market_trend": "",
    "market_risk_level": "",
    "focus_sectors": [],
    "excluded_sectors": [],
    "reality_summary": "",
    "source_report": ""
  },
  "hexagram_manual_input": {
    "hexagram_status": "NOT_PROVIDED",
    "adjustment_rule": "DOWNGRADE_ONLY"
  },
  "weekly_strategy": {
    "participation_level": "",
    "allowed_sectors": [],
    "prohibited_sectors": []
  },
  "night_plan": {
    "planned_quantity": 100,
    "plan_status": "NOT_READY"
  },
  "intraday_veto_result": {
    "check_time_window": "09:50-10:00",
    "data_status": "NOT_CHECKED"
  },
  "daily_execution_state": {
    "new_buy_locked": false,
    "new_position_opened_today": false
  }
}
```

结构约束：

1. `focus_sectors` 最多两个。
2. `hexagram_status` 只允许 `NOT_PROVIDED / PROVIDED`。
3. `adjustment_rule` 固定为 `DOWNGRADE_ONLY`。
4. `participation_level` 只允许空值、`NORMAL_TRIAL`、`CAUTIOUS_TRIAL`、`NO_NEW_BUY`。
5. `planned_quantity` 固定为 100。
6. `check_time_window` 固定为 `09:50-10:00`。

## 3. 支持的阶段转换

| 当前阶段 | 允许下一阶段 |
|---|---|
| WEEKEND_REALITY_PENDING | WEEKEND_REALITY_PENDING / WEEKEND_HEXAGRAM_PENDING |
| WEEKEND_HEXAGRAM_PENDING | WEEKEND_HEXAGRAM_PENDING / WEEKLY_STRATEGY_READY |
| WEEKLY_STRATEGY_READY | WEEKLY_STRATEGY_READY / NIGHT_PLAN_READY |
| NIGHT_PLAN_READY | NIGHT_PLAN_READY / INTRADAY_CHECK_PENDING |
| INTRADAY_CHECK_PENDING | INTRADAY_CHECK_PENDING / INTRADAY_CHECK_COMPLETED |
| INTRADAY_CHECK_COMPLETED | INTRADAY_CHECK_COMPLETED / CLOSING_REVIEW_COMPLETED |
| CLOSING_REVIEW_COMPLETED | CLOSING_REVIEW_COMPLETED / WEEKLY_REVIEW_COMPLETED |
| WEEKLY_REVIEW_COMPLETED | WEEKLY_REVIEW_COMPLETED / WEEKEND_REALITY_PENDING |

说明：允许同阶段更新，是为了人工补字段、修正记录和补录说明。跨阶段跳转会报错。

## 4. 最小工具能力

命令行入口：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts\run_workflow_state_tool.py create --latest-completed-trade-date 20260717
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts\run_workflow_state_tool.py read
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts\run_workflow_state_tool.py validate
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts\run_workflow_state_tool.py render
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 scripts\run_workflow_state_tool.py update-section --section weekend_reality_analysis --updates-json "{...}" --next-stage WEEKEND_HEXAGRAM_PENDING
```

模块入口：

| 函数 | 用途 |
|---|---|
| `create_blank_state` | 创建空白骨架 |
| `load_state` | 读取并校验 JSON |
| `save_state` | 保存 JSON 并同步生成 Markdown |
| `update_section` | 更新指定部分并检查阶段转换 |
| `validate_state` | JSON 结构校验 |
| `render_markdown` | 生成人类可读 Markdown |

## 5. 新增测试结果

已按测试先行方式添加 `tests/test_workflow_state_scaffold.py`。本轮新增测试覆盖：

1. 可以创建空白状态文件。
2. 可以写入周末现实分析。
3. 可以写入六爻人工结果。
4. 可以写入前夜首选和替补。
5. 可以写入盘中否决结果。
6. 可以写入收盘和周度复盘。
7. 非法阶段转换会报错。
8. Markdown 能够正确生成。
9. 保存后的 JSON 能通过结构校验。

新增测试命令：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 -m pytest tests\test_workflow_state_scaffold.py -q
```

结果：`9 passed`。

## 6. 现有测试是否全部通过

已执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_project_python.ps1 -m pytest -q
```

结果：`65 passed`。

## 7. 与现有项目是否重复

未发现功能相同的连续周度工作流状态系统。

已存在但用途不同的结构：

| 现有文件/结构 | 用途 | 是否复用 |
|---|---|---|
| `reports/workflow/latest_workflow_status.json/md` | 检查数据层、评分层、报告层、交互层是否可用 | 不复用为交易计划状态；保留为健康检查报告 |
| `reports/workflow/daily_workflow_latest.json/md` | 日常脚本运行步骤和输出状态 | 不复用为周度连续状态；可作为后续 source_report |
| `reports/simulated_live_v1/state/simulated_account_state.json` | 模拟账户资金和持仓状态 | 不复用为策略流程状态，避免混淆账户和研究计划 |
| `config/realtime_watchlist.json` | 只读实时盯盘配置 | 不复用为计划状态，后续盘中阶段可读取其结果，但本轮不修改 |
| `股票策略研究室` 下 weekly/hexagram 模板 | 独立研究室模板 | 只作为参考，不并入主项目状态骨架 |

本轮选择复用 `reports/workflow/` 目录和现有“JSON + Markdown”输出风格，新增 `current_workflow_state.json/md` 作为连续工作流状态入口。

## 8. 后续接入建议

1. 下一轮先实现“周末现实分析写入器”：只把人工或已有报告结论写入 `weekend_reality_analysis`，不自动选股。
2. 再实现“六爻人工结果录入器”：只录入用户提供内容，并保持 `DOWNGRADE_ONLY`。
3. 再实现“前夜计划写入器”：写首选、替补、100 股、取消条件。
4. 最后再让 C 模块盘中否决读取这个状态文件；本轮尚未接入。
