from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = 'https://fuyao.aicubes.cn'
MINUTE_FREQUENCIES = {'1m': 8, '5m': 0, '15m': 1, '30m': 2, '60m': 3}
ENDPOINTS = json.loads((ROOT / 'config/data_endpoints.json').read_text(encoding='utf-8'))

class DataSourceError(RuntimeError):
    pass

def credentials():
    key = os.environ.get('HITHINK_FINANCE_API_KEY', '').strip()
    if key:
        return key, 'environment'
    if sys.platform == 'win32':
        path = Path(os.environ.get('APPDATA', '')) / 'hithink-finance/credentials.env'
    elif sys.platform == 'darwin':
        path = Path.home() / 'Library/Application Support/hithink-finance/credentials.env'
    else:
        path = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'hithink-finance/credentials.env'
    if path.is_file():
        for line in path.read_text(encoding='utf-8').splitlines():
            k, sep, v = line.strip().partition('=')
            if sep and k == 'HITHINK_FINANCE_API_KEY' and v.strip().strip('\"\''):
                return v.strip().strip('\"\''), 'credentials.env'
    raise DataSourceError('hithink-finance: HITHINK_FINANCE_API_KEY missing')

def request(capability, **params):
    if capability not in ENDPOINTS:
        raise DataSourceError(f'hithink-finance: unsupported capability {capability}; no fallback')
    key, _ = credentials()
    url = BASE_URL + ENDPOINTS[capability] + '?' + urlencode(params)
    req = Request(url, headers={'X-api-key': key, 'Accept': 'application/json'})
    for attempt in range(3):
        try:
            with urlopen(req, timeout=15) as response:
                payload = json.load(response)
            if payload.get('code') != 0:
                code = payload.get('code')
                if (code == 4001 or str(code).startswith('5')) and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                raise DataSourceError(f'hithink-finance: code={code}, request_id={payload.get("request_id")}; no fallback')
            if payload.get('data') is None:
                raise DataSourceError('hithink-finance: null data; no fallback')
            return {'source': 'hithink-finance', 'capability': capability,
                    'fetched_at': datetime.now(timezone.utc).isoformat(),
                    'request_id': payload.get('request_id'), 'data': payload['data']}
        except HTTPError as exc:
            if (exc.code == 429 or exc.code >= 500) and attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise DataSourceError(f'hithink-finance: HTTP {exc.code}; no fallback') from None
        except (URLError, TimeoutError, OSError) as exc:
            if attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise DataSourceError(f'hithink-finance: {type(exc).__name__} after 3 attempts; no fallback') from None
        except (ValueError, TypeError) as exc:
            raise DataSourceError(f'hithink-finance: invalid response ({type(exc).__name__}); no fallback') from None

def snapshot(thscode):
    result = request('snapshot', thscodes=thscode)
    rows = result['data'].get('item')
    if not rows or len(rows) != 1 or rows[0].get('thscode') != thscode or rows[0].get('last_price') is None:
        raise DataSourceError('hithink-finance: snapshot missing or symbol mismatch; no fallback')
    # Explicit-symbol snapshots may omit source timestamp; never replace it with fetch time.
    return result

def minutes(thscode, interval='1m', count=5):
    if interval not in MINUTE_FREQUENCIES or not 1 <= count <= 800:
        raise DataSourceError('mootdx: interval must be 1m/5m/15m/30m/60m; count must be 1..800')
    if not re.fullmatch(r'\d{6}\.(SH|SZ)', thscode):
        raise DataSourceError('mootdx: requires a verified SH/SZ security code; other markets not validated')
    try:
        # Keep the library cache inside this project, never write to the user home.
        from unittest.mock import patch
        cache = ROOT / '.cache'
        cache.mkdir(parents=True, exist_ok=True)
        with patch('pathlib.Path.home', return_value=cache):
            from mootdx.quotes import Quotes
            import mootdx.config
        conf = cache / '.mootdx/config.json'
        mootdx.config.CONF = str(conf)
        if not conf.exists():
            conf.write_text(json.dumps(mootdx.config.settings), encoding='utf-8')
        kwargs = dict(market='std', server=('110.41.147.114', 7709), timeout=5, heartbeat=False, auto_retry=False, raise_exception=True)
        host = os.environ.get('MOOTDX_SERVER')
        if host:
            address, port = host.rsplit(':', 1)
            kwargs['server'] = (address, int(port))
        client = Quotes.factory(**kwargs)
        try:
            frame = client.bars(symbol=thscode[:6], frequency=MINUTE_FREQUENCIES[interval], start=0, offset=count)
        finally:
            client.close()
        required = {'datetime', 'open', 'high', 'low', 'close', 'vol', 'amount'}
        if frame is None or frame.empty or not required.issubset(frame.columns):
            raise DataSourceError('mootdx: empty or malformed minute data; no fallback')
        frame = frame.sort_values('datetime')
        if frame[list(required)].isnull().any().any() or (frame['close'] <= 0).any():
            raise DataSourceError('mootdx: invalid minute values; no fallback')
        rows = json.loads(frame[list(sorted(required))].to_json(orient='records', date_format='iso'))
        return {'source': 'mootdx', 'thscode': thscode, 'interval': interval, 'adjust': 'none',
                'volume_unit': 'lot', 'amount_unit': 'CNY', 'timezone': 'Asia/Shanghai',
                'fetched_at': datetime.now(timezone.utc).isoformat(), 'data': rows}
    except DataSourceError:
        raise
    except Exception as exc:
        raise DataSourceError(f'mootdx: {type(exc).__name__}; no fallback') from None

def require_current_source(payload):
    source = payload.get('source') or payload.get('data_source') or payload.get('quote_data_source')
    if source not in {'hithink-finance', 'mootdx'}:
        raise DataSourceError('Cached data source is retired or unknown; fetch fresh data from configured sources')
    if source == 'mootdx' and payload.get('interval') not in MINUTE_FREQUENCIES:
        raise DataSourceError('mootdx may only supply minute bars')
    return payload

def main(argv=None):
    parser = argparse.ArgumentParser(description='Strict hithink-finance / mootdx data gateway')
    parser.add_argument('capability', choices=sorted(ENDPOINTS) + ['minutes', 'smoke', 'auth-status'])
    parser.add_argument('--thscode', default='600519.SH')
    parser.add_argument('--interval', default='1m', choices=MINUTE_FREQUENCIES)
    parser.add_argument('--count', type=int, default=5)
    parser.add_argument('--params', default='{}', help='Official endpoint query parameters as JSON')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.capability == 'auth-status':
            _, origin = credentials()
            result = {'present': True, 'origin': origin, 'availability': 'not_tested'}
        elif args.capability == 'smoke':
            result = {}
            for name, fn in [('hithink-finance', lambda: snapshot(args.thscode)), ('mootdx', lambda: minutes(args.thscode, args.interval, args.count))]:
                try:
                    result[name] = {'ok': True, 'result': fn()}
                except DataSourceError as exc:
                    result[name] = {'ok': False, 'error': str(exc)}
        elif args.capability == 'minutes':
            result = minutes(args.thscode, args.interval, args.count)
        elif args.capability == 'snapshot':
            result = snapshot(args.thscode)
        else:
            result = request(args.capability, **json.loads(args.params))
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding='utf-8')
            print(json.dumps({'output': str(args.output), 'capability': args.capability}))
        else:
            print(encoded)
        return 2 if args.capability == 'smoke' and not all(x['ok'] for x in result.values()) else 0
    except (DataSourceError, ValueError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
