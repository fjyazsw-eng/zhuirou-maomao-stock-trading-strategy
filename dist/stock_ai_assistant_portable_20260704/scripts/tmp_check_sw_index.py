import os

import tushare as ts

pro = ts.pro_api(os.getenv("TUSHARE_TOKEN"))
for code in ["801084.SI", "850813.SI", "850861.SI"]:
    df = pro.index_daily(
        ts_code=code,
        start_date="20260601",
        end_date="20260701",
        fields="ts_code,trade_date,close,pre_close,pct_chg,amount",
    )
    print(code, len(df))
    print(df.head(2).to_string(index=False))
