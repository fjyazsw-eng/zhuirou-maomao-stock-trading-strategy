"""Retired provider compatibility names; all supported calls use HiThink only.

Unsupported legacy schemas fail explicitly instead of changing provider or fabricating fields.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path
import os
import pandas as pd
from scoring_system.market_data import request, credentials, DataSourceError

def load_dotenv(root=None):
    # Legacy callers may load non-secret application settings, never provider tokens.
    return None

def token_value():
    return ''
def replay_api_key():
    return ''
def http_url_value():
    return ''
def should_use_env_proxy_for_url(url):
    return True

def _date_ms(value):
    return int(datetime.strptime(value, '%Y%m%d').replace(tzinfo=timezone(timedelta(hours=8))).timestamp()*1000)

class HiThinkLegacyAdapter:
    def query(self, api_name, fields='', **kwargs):
        if api_name == 'daily' and kwargs.get('ts_code'):
            symbol=kwargs['ts_code']
            start=kwargs.get('start_date') or kwargs.get('trade_date')
            end=kwargs.get('end_date') or kwargs.get('trade_date')
            if not start or not end:
                raise DataSourceError('hithink-finance: daily requires explicit date range')
            result=request('a-share.prices.historical',thscode=symbol,interval='1d',start=_date_ms(start),end=_date_ms(end)+86399999,adjust='none')
            rows=result['data'].get('item')
            if not rows:
                raise DataSourceError('hithink-finance: daily data empty')
            frame=pd.DataFrame(rows).rename(columns={'open_price':'open','high_price':'high','low_price':'low','close_price':'close'})
            frame['trade_date']=pd.to_datetime(frame['date_ms'],unit='ms',utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y%m%d')
            frame['ts_code']=symbol
            frame['vol']=frame['volume']/100 # Legacy daily expects lots.
            frame['amount']=frame['turnover']/1000 # Legacy daily expects thousand yuan.
            frame=frame.sort_values('trade_date')
            frame['pre_close']=frame['close'].shift(1)
            frame['change']=frame['close']-frame['pre_close']
            frame['pct_chg']=frame['change']/frame['pre_close']*100
            frame=frame.sort_values('trade_date',ascending=False)
        elif api_name == 'trade_cal':
            result=request('a-share.calendar.trading-days')
            rows=result['data'].get('item') or []
            if not rows:raise DataSourceError('hithink-finance: trading calendar empty')
            frame=pd.DataFrame({'cal_date':[str(x['date']) for x in rows]})
            start=kwargs.get('start_date',frame['cal_date'].min());end=kwargs.get('end_date',frame['cal_date'].max())
            if start < frame['cal_date'].min() or end > frame['cal_date'].max() or str(kwargs.get('is_open','1')) != '1':
                raise DataSourceError('hithink-finance: requested calendar range/closed dates not supported; no fabricated dates')
            frame=frame[(frame.cal_date>=start)&(frame.cal_date<=end)].copy();frame['is_open']=1
        else:
            raise DataSourceError(f'hithink-finance: legacy schema {api_name} is not supported; use market_data public capability with official parameters; no fallback')
        if fields:
            missing=set(fields.split(','))-set(frame.columns)
            if missing:raise DataSourceError('hithink-finance: requested legacy fields not available: '+','.join(sorted(missing)))
            frame=frame[fields.split(',')]
        frame.attrs['source']='hithink-finance'
        return frame
    def __getattr__(self,name):
        return lambda **kwargs:self.query(name,**kwargs)

def get_tushare_pro(root=None):
    credentials()
    return HiThinkLegacyAdapter()

def pro_api(*args,**kwargs):
    return get_tushare_pro()

def set_token(*args,**kwargs):
    raise DataSourceError('Tushare is disabled; use HITHINK_FINANCE_API_KEY')

class ReplayDataApi:
    def __init__(self,*args,**kwargs):
        raise DataSourceError('Tushare replay is disabled; no fallback')
HttpPostDataApi=ReplayDataApi

def build_session(*args,**kwargs):
    raise DataSourceError('Legacy provider sessions disabled; use market_data gateway')
def patch_replay_dns():
    raise DataSourceError('Tushare replay DNS is disabled')


def credential_marker():
    try:
        credentials()
        return 'configured'
    except DataSourceError:
        return ''
