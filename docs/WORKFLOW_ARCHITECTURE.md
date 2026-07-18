# 股票AI交易助手工作流架构

## 1. 模块关系

- 总控 Skill：`skills/stock-ai-workflow-controller/SKILL.md`
  - 负责新 Codex 的阅读顺序、优先级、禁止事项和输出格式。
- 统一入口：`scripts/run_project.py`
  - 只做命令路由，不重复实现业务逻辑。
- 环境检查：`scoring_system/portable_setup_check.py`
  - 检查 Python、依赖、Token、连接、状态文件、核心模块和报告目录。
- 状态骨架：`scoring_system/workflow_state.py`
  - 负责状态创建、读取、指定区块更新、结构校验和 Markdown 渲染。
- 工作流编排：`scoring_system/workflow_orchestrator.py`
  - 负责周末、六爻、周度策略、前夜计划、盘中否决、收盘复盘、周度复盘和反转观察的阶段流转。
- 系统性风险总闸：`scoring_system/systemic_risk_gate.py`
  - 只判断是否禁止新买入，不决定持仓卖出。
- 人工六爻校准：`scoring_system/hexagram_calibration.py`
  - 只接收人工结构化输入，只降级不升级。
- 第六轮演练器：`scoring_system/workflow_release_drill.py`
  - 用固定夹具做封版前联合演练和安全审查，不调用真实交易。

## 2. 状态流转

主阶段：

1. `WEEKEND_REALITY_PENDING`
2. `WEEKEND_HEXAGRAM_PENDING`
3. `WEEKLY_STRATEGY_READY`
4. `NIGHT_PLAN_READY`
5. `INTRADAY_CHECK_PENDING`
6. `INTRADAY_CHECK_COMPLETED`
7. `CLOSING_REVIEW_COMPLETED`
8. `WEEKLY_REVIEW_COMPLETED`

周五复盘后，下一周重新回到 `WEEKEND_REALITY_PENDING`。真实运行必须保留上周归档，不能覆盖历史记录。

## 3. 固定优先级

1. 数据可靠性
2. 系统性风险总闸
3. 现实市场分析
4. 人工六爻只降级校准
5. 前夜候选
6. 盘中否决
7. 持仓管理
8. 复盘

低层规则不得覆盖高层禁止条件。

## 4. 数据流

- Tushare：盘后完整日线、历史行情、指数、基础数据和财务数据。
- 东方财富：只读盘中临时行情、指数、个股、板块和分时状态。
- 人工六爻：人工整理后的结构化结论，只作为降级校准输入。
- workflow state：贯穿周末、前夜、盘中、收盘和周度复盘的唯一状态文件。

不得用盘中临时数据冒充 Tushare 完整日线，不得使用未来数据倒灌。

## 5. 报告流

- 当前状态：`reports/workflow/current_workflow_state.json`
- 人类可读状态：`reports/workflow/current_workflow_state.md`
- 示例状态：`reports/workflow/current_workflow_state.example.json`
- 阶段报告：`reports/workflow/*.md`
- 历史归档：`reports/workflow/history/`

真实状态和历史归档可能包含个人记录，默认不提交。

## 6. 故障停止点

必须停止并报告：

- 环境检查为 `NOT_READY`。
- workflow state JSON 损坏。
- 当前阶段非法。
- 数据缺失、过期或不一致。
- 系统性风险总闸锁定。
- 前夜计划缺失时直接盘中检查。
- 同一有效六爻问题重复录入。
- 历史目录不可写。
- 核心模块导入失败。

停止时只报告问题和恢复建议，不自动覆盖损坏状态。

## 7. Skill和代码分工

- Skill 负责行为边界、阅读顺序、优先级和禁止事项。
- 代码负责状态校验、阶段流转、固定映射和可重复测试。
- 文档负责新 Codex 和新电脑迁移，不承载真实 Token、真实持仓或个人账户信息。
