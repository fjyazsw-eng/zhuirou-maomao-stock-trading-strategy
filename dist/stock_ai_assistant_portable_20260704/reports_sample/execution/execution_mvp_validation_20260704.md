# 执行标签与仓位模块MVP小样本验证 20260704

说明：本验证只检查执行层降级和仓位映射，不重跑原七题，不做回测，不修改评分权重。

| 样本 | 股票 | 角色 | 原始状态 | 最终执行标签 | 允许买 | 最大仓位 | 板块周期 | 主要原因 |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- |
| 半导体高位样本 | 有研新材 600206.SH | 容量核心 | READY_CONFIRM | OVERHEATED_NO_CHASE | 否 | 0% | CLIMAX + HIGH_LEVEL_UNSTABLE / CLIMAX_FADING_RISK，HIGH | 板块处于高潮或高潮后退潮风险，空仓不追高。 |
| 半导体高位样本（不能盯盘） | 有研新材 600206.SH | 容量核心 | READY_CONFIRM | OBSERVE_ONLY | 否 | 0% | CLIMAX + HIGH_LEVEL_UNSTABLE / CLIMAX_FADING_RISK，HIGH | 板块处于高潮或高潮后退潮风险，空仓不追高。；不能盯盘且板块处于高潮、分歧或退潮，不新开仓。 |
| 半导体高位样本（持仓） | 有研新材 600206.SH | 容量核心 | READY_CONFIRM | HOLD_WITH_PROTECTION | 否 | 0% | CLIMAX + HIGH_LEVEL_UNSTABLE / CLIMAX_FADING_RISK，HIGH | 板块处于高潮或高潮后退潮风险，空仓不追高。 |
| 半导体高位样本（后排） | 盛合晶微 688820.SH | 后排或弱结构 | WAIT_CONFIRM | OVERHEATED_NO_CHASE | 否 | 0% | CLIMAX + HIGH_LEVEL_UNSTABLE / CLIMAX_FADING_RISK，HIGH | 原始状态仍需等待确认。；板块处于高潮或高潮后退潮风险，空仓不追高。 |
| 电子化学品分歧样本 | 鼎龙股份 300054.SZ | 容量核心 | READY_CONFIRM | WAIT_FOR_SUPPORT | 否 | 0% | DIVERGENCE + HIGH_LEVEL_UNSTABLE / WAIT_FOR_CONFIRMATION / BACKROW_RISK_SPREAD，MEDIUM | 板块分歧，空仓等待承接。 |
| 电子化学品分歧样本（不能盯盘） | 鼎龙股份 300054.SZ | 容量核心 | READY_CONFIRM | OBSERVE_ONLY | 否 | 0% | DIVERGENCE + HIGH_LEVEL_UNSTABLE / WAIT_FOR_CONFIRMATION / BACKROW_RISK_SPREAD，MEDIUM | 板块分歧，空仓等待承接。；不能盯盘且板块处于高潮、分歧或退潮，不新开仓。 |
| 电子化学品分歧样本（持仓） | 鼎龙股份 300054.SZ | 容量核心 | READY_CONFIRM | WAIT_FOR_SUPPORT | 否 | 0% | DIVERGENCE + HIGH_LEVEL_UNSTABLE / WAIT_FOR_CONFIRMATION / BACKROW_RISK_SPREAD，MEDIUM | 板块分歧，空仓等待承接。 |
| 电子化学品分歧样本（后排） | 思泉新材 301489.SZ | 后排或弱结构 | WAIT_CONFIRM | BREAKDOWN_AVOID | 否 | 0% | DIVERGENCE + HIGH_LEVEL_UNSTABLE / WAIT_FOR_CONFIRMATION / BACKROW_RISK_SPREAD，MEDIUM | 原始状态仍需等待确认。；板块分歧，空仓等待承接。 |
| 航天装备结构性机会样本 | 中国卫星 600118.SH | 容量核心 | READY_CONFIRM | READY_TRIAL | 是 | 10% | UNKNOWN + STRUCTURAL_START / NON_MAINLINE_OPPORTUNITY / BACKROW_RISK_SPREAD，MEDIUM | 无明显降级。 |
| 航天装备结构性机会样本（不能盯盘） | 中国卫星 600118.SH | 容量核心 | READY_CONFIRM | OBSERVE_ONLY | 否 | 0% | UNKNOWN + STRUCTURAL_START / NON_MAINLINE_OPPORTUNITY / BACKROW_RISK_SPREAD，MEDIUM | 用户不能盯盘，执行标签自动降级。；仓位规则将 READY_TRIAL 降级为 OBSERVE_ONLY。 |
| 航天装备结构性机会样本（持仓） | 中国卫星 600118.SH | 容量核心 | READY_CONFIRM | READY_TRIAL | 否 | 0% | UNKNOWN + STRUCTURAL_START / NON_MAINLINE_OPPORTUNITY / BACKROW_RISK_SPREAD，MEDIUM | 无明显降级。 |
| 航天装备结构性机会样本（后排） | 新余国科 300722.SZ | 后排或弱结构 | WAIT_CONFIRM | OBSERVE_ONLY | 否 | 0% | UNKNOWN + STRUCTURAL_START / NON_MAINLINE_OPPORTUNITY / BACKROW_RISK_SPREAD，MEDIUM | 原始状态仍需等待确认。；结构性启动阶段只看核心，后排不参与。 |
| 最新日常候选 20260702 | 潮宏基 002345.SZ | MULTI_CORE | WAIT_PULLBACK_CORE | OBSERVE_ONLY | 否 | 0% | STARTING + STRUCTURAL_START / WEAK_TO_STRONG_WATCH，LOW | 原始状态提示短期过热或等待回踩。；板块置信度低，只允许观察或小试错。 |
| 最新日常候选 20260702 | 拉芳家化 603630.SH | FOLLOWER | WAIT_CONFIRM | OBSERVE_ONLY | 否 | 0% | STARTING + STRUCTURAL_START / WEAK_TO_STRONG_WATCH，LOW | 原始状态仍需等待确认。；结构性启动阶段只看核心，后排不参与。 |
| 最新日常候选 20260702 | 百合花 603823.SH | MULTI_CORE | WAIT_PULLBACK_CORE | OBSERVE_ONLY | 否 | 0% | STARTING + STRUCTURAL_START / WEAK_TO_STRONG_WATCH，LOW | 原始状态提示短期过热或等待回踩。；板块置信度低，只允许观察或小试错。 |
| 最新日常候选 20260702 | 科伦药业 002422.SZ | MULTI_CORE | WAIT_PULLBACK_CORE | OBSERVE_ONLY | 否 | 0% | STARTING + STRUCTURAL_START / WEAK_TO_STRONG_WATCH，LOW | 原始状态提示短期过热或等待回踩。；板块置信度低，只允许观察或小试错。 |
| 最新日常候选 20260702 | 温氏股份 300498.SZ | FOLLOWER | WAIT_CONFIRM | OBSERVE_ONLY | 否 | 0% | STARTING + STRUCTURAL_START / WEAK_TO_STRONG_WATCH，LOW | 原始状态仍需等待确认。；结构性启动阶段只看核心，后排不参与。 |
| 最新日常候选 20260702 | 益生股份 002458.SZ | SECONDARY | WAIT_CONFIRM | OBSERVE_ONLY | 否 | 0% | STARTING + STRUCTURAL_START / WEAK_TO_STRONG_WATCH，LOW | 原始状态仍需等待确认。；板块置信度低，只允许观察或小试错。 |
| 最新日常候选 20260702 | 赤峰黄金 600988.SH | CORE | WEAK_STRUCTURE | BREAKDOWN_AVOID | 否 | 0% | STARTING + STRUCTURAL_START / WEAK_TO_STRONG_WATCH，LOW | 原始状态偏弱。；板块置信度低，只允许观察或小试错。 |
| 最新日常候选 20260702 | 昊华科技 600378.SH | MULTI_CORE | WAIT_PULLBACK_CORE | OBSERVE_ONLY | 否 | 0% | STARTING + STRUCTURAL_START / WEAK_TO_STRONG_WATCH，LOW | 原始状态提示短期过热或等待回踩。；板块置信度低，只允许观察或小试错。 |

## 验证结论

- 半导体高位样本：高潮和高潮后退潮风险会压制新买，高分核心不再直接追高，持仓转向利润保护。
- 电子化学品分歧样本：分歧状态会让空仓等待承接，后排和不能盯盘场景会进一步降级。
- 航天装备结构性机会样本：结构性启动允许核心观察仓或小试错仓，但不会放大成全面强势。
- 最新日常候选：每只候选都能输出最终执行标签、允许买、最大仓位和降级原因。

边界：这是最小可用执行层验证，不代表完整回测收益，也不是交易指令。