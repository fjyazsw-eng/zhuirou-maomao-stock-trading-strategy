# 持仓管理规则

持仓标签：HOLD_NORMAL、HOLD_WITH_PROTECTION、REDUCE_PROFIT_PROTECTION、REDUCE_RISK、EXIT_STOP_LOSS、EXIT_LOGIC_BROKEN、NO_ADD_WAIT_SUPPORT、WATCH_ONLY_HOLDING、CORE_HOLD_BACKROW_REDUCE、NO_WATCH_REDUCE。

浮盈：

- 0%到3%：不视为安全利润。
- 3%到8%：持有但保护。
- 8%以上：必须利润保护。

浮亏：

- 0%到-3%：正常波动。
- -3%到-6%：风险观察，禁止补仓。
- 超过-6%：判断逻辑是否破坏。

不能盯盘：自动降级，不加仓，保护线提前设置。
