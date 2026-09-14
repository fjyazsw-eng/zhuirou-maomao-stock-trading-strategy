from scoring_system.tushare_client import credential_marker
import os

from scoring_system import tushare_client as ts

pro = ts.pro_api(credential_marker())
try:
    df = pro.margin_detail(
        trade_date="20260630",
        fields="trade_date,ts_code,rzye,rqye,rzmre,rzche",
    )
    print(len(df))
    print(df.head().to_string(index=False))
except Exception as exc:
    print(type(exc).__name__, exc)
