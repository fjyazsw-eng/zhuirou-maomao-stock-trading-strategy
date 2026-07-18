import os

import tushare as ts

pro = ts.pro_api(os.getenv("TUSHARE_TOKEN"))
try:
    df = pro.margin_detail(
        trade_date="20260630",
        fields="trade_date,ts_code,rzye,rqye,rzmre,rzche",
    )
    print(len(df))
    print(df.head().to_string(index=False))
except Exception as exc:
    print(type(exc).__name__, exc)
