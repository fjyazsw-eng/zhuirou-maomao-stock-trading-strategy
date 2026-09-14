from __future__ import annotations
from datetime import datetime,timezone,timedelta
from scoring_system.market_data import snapshot,DataSourceError

def fetch_realtime_quote(code):
    if '.' not in code:
        from scoring_system.market_data import request
        rows=request('meta.tickers.search',q=code,limit=10)['data'].get('item',[])
        matches=[r for r in rows if r.get('ticker')==code and r.get('thscode','').endswith(('.SH','.SZ','.BJ'))]
        if len(matches)!=1:raise DataSourceError('hithink-finance: symbol is ambiguous or missing')
        code=matches[0]['thscode']
    result=snapshot(code);data=result['data'];row=data['item'][0]
    stamp=data.get('timestamp')
    date=datetime.fromtimestamp(stamp/1000,timezone(timedelta(hours=8))).strftime('%Y%m%d') if stamp else '-'
    def val(k):return str(row[k]) if row.get(k) is not None else '-'
    return {'source':'hithink-finance','ts_code':code,'name':code,'trade_date':date,
            'price':val('last_price'),'pct_chg':val('price_change_ratio_pct')+'%',
            'open':val('open_price'),'high':val('high_price'),'low':val('low_price'),
            'prev_close':val('prev_price'),'amount':val('turnover')}
