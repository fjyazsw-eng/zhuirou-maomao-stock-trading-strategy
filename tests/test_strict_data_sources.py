"""Contract tests only; mocked responses below are not market observations."""
import json
import unittest
from io import BytesIO
from unittest.mock import patch
from scoring_system import market_data as m
from scoring_system import tushare_client as legacy

class GatewayTests(unittest.TestCase):
    def response(self,data):return BytesIO(json.dumps(data).encode())
    def test_auth_does_not_reuse_retired_tokens(self):
        with patch.dict(m.os.environ,{'TUSHARE_TOKEN':'test-only'},clear=True),patch.object(m.Path,'is_file',return_value=False):
            with self.assertRaises(m.DataSourceError):m.credentials()
    def test_error_envelope_never_falls_back(self):
        with patch.object(m,'credentials',return_value=('test-only','test')),patch.object(m,'urlopen',return_value=self.response({'code':2003,'data':None})) as remote,patch.object(m,'minutes') as fallback:
            with self.assertRaises(m.DataSourceError):m.request('snapshot',thscodes='600519.SH')
            self.assertEqual(remote.call_count,1);fallback.assert_not_called()
    def test_null_payload_is_failure(self):
        with patch.object(m,'credentials',return_value=('test-only','test')),patch.object(m,'urlopen',return_value=self.response({'code':0,'data':None})):
            with self.assertRaises(m.DataSourceError):m.request('snapshot')
    def test_missing_quote_is_failure(self):
        with patch.object(m,'request',return_value={'data':{'item':[]}}):
            with self.assertRaises(m.DataSourceError):m.snapshot('600519.SH')
    def test_symbol_mismatch_is_failure(self):
        with patch.object(m,'request',return_value={'data':{'item':[{'thscode':'000001.SZ','last_price':1}]}}):
            with self.assertRaises(m.DataSourceError):m.snapshot('600519.SH')
    def test_unknown_provider_cannot_receive_key(self):
        with patch.object(m,'credentials') as cred:
            with self.assertRaises(m.DataSourceError):m.request('https://other.example')
            cred.assert_not_called()
    def test_daily_cannot_use_minute_provider(self):
        with self.assertRaises(m.DataSourceError):m.minutes('600519.SH','1d')
    def test_minute_count_is_bounded(self):
        with self.assertRaises(m.DataSourceError):m.minutes('600519.SH','1m',801)
    def test_all_frequencies(self):
        self.assertEqual(m.MINUTE_FREQUENCIES,{'1m':8,'5m':0,'15m':1,'30m':2,'60m':3})
    def test_retired_replay_disabled(self):
        with self.assertRaises(m.DataSourceError):legacy.ReplayDataApi('test-only')
        with self.assertRaises(m.DataSourceError):legacy.HttpPostDataApi('test-only','https://other.example')
    def test_unsupported_legacy_schema_is_explicit(self):
        with self.assertRaises(m.DataSourceError):legacy.HiThinkLegacyAdapter().query('daily_basic')
    def test_old_cache_rejected(self):
        for source in ['tushare_direct','eastmoney_realtime',None]:
            with self.assertRaises(m.DataSourceError):m.require_current_source({'source':source})
    def test_mootdx_cannot_label_daily(self):
        with self.assertRaises(m.DataSourceError):m.require_current_source({'source':'mootdx','interval':'1d'})
    def test_no_active_sdk_imports(self):
        import ast
        for folder in ['scoring_system','scripts','股票策略研究室/scripts']:
            for path in (m.ROOT/folder).rglob('*.py'):
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                    if isinstance(node,ast.Import):
                        self.assertFalse(any(a.name in {'tushare','akshare','baostock'} for a in node.names),str(path))
if __name__=='__main__':unittest.main()
