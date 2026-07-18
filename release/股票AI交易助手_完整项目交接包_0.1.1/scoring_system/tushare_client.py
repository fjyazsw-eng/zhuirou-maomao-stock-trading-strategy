from __future__ import annotations

import os
import socket
from functools import partial
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from scoring_system.network_env import clear_bad_tushare_proxy

REPLAY_BASE_URLS = [
    "http://127.0.0.1:8000/tushare/pro",
    "https://ai-tool.indevs.in/tushare/pro",
    "https://tushare.indevs.in/tushare/pro",
]

DNS_FALLBACKS = {
    "ai-tool.indevs.in": ["172.67.197.91"],
    "tushare.indevs.in": ["172.67.197.91"],
}

_DNS_PATCHED = False
_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_ORIGINAL_GETHOSTBYNAME = socket.gethostbyname


def load_dotenv(root: str | os.PathLike[str] | None = None) -> None:
    env_path = os.path.join(str(root or os.getcwd()), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            force_project_value = key in {
                "TUSHARE_TOKEN",
                "TUSHARE_TOKEN_PRO",
                "TUSHARE_HTTP_URL",
                "TUSHARE_API_URL",
                "TUSHARE_REPLAY_API_KEY",
            }
            if key and (force_project_value or key not in os.environ):
                os.environ[key] = value


def _normalize_host(host: Any) -> Any:
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    return host.rstrip(".") if isinstance(host, str) else host


def patch_replay_dns() -> None:
    global _DNS_PATCHED
    if _DNS_PATCHED:
        return

    def _getaddrinfo(host: Any, port: Any, family: int = 0, type: int = 0, proto: int = 0, flags: int = 0) -> Any:
        try:
            return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)
        except socket.gaierror:
            fallback_ips = DNS_FALLBACKS.get(_normalize_host(host))
            if not fallback_ips:
                raise
            results: list[Any] = []
            for fallback_ip in fallback_ips:
                try:
                    results.extend(_ORIGINAL_GETADDRINFO(fallback_ip, port, family, type, proto, flags))
                except socket.gaierror:
                    continue
            if not results:
                raise
            return results

    def _gethostbyname(host: Any) -> Any:
        try:
            return _ORIGINAL_GETHOSTBYNAME(host)
        except socket.gaierror:
            fallback_ips = DNS_FALLBACKS.get(_normalize_host(host))
            if not fallback_ips:
                raise
            return fallback_ips[0]

    socket.getaddrinfo = _getaddrinfo
    socket.gethostbyname = _gethostbyname
    _DNS_PATCHED = True


def replay_api_key() -> str:
    return os.environ.get("TUSHARE_REPLAY_API_KEY", "")


def token_value() -> str:
    return os.environ.get("TUSHARE_TOKEN", "") or os.environ.get("TUSHARE_TOKEN_PRO", "")


def http_url_value() -> str:
    return os.environ.get("TUSHARE_HTTP_URL", "") or os.environ.get("TUSHARE_API_URL", "")


def build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"Accept": "application/json", "User-Agent": "tushare-relay-client/1.2"})
    session.trust_env = False
    session.proxies.update({"http": "", "https": ""})
    return session


def payload_to_frame(payload: dict[str, Any]) -> pd.DataFrame:
    data = payload.get("data")
    if isinstance(data, dict):
        fields = data.get("fields") or []
        items = data.get("items") or []
        return pd.DataFrame(items, columns=fields)
    if isinstance(data, list):
        return pd.DataFrame(data)
    return pd.DataFrame()


class ReplayDataApi:
    def __init__(self, api_key: str, base_urls: list[str] | None = None, timeout: int = 30) -> None:
        self.api_key = api_key
        self.base_urls = base_urls or REPLAY_BASE_URLS
        self.timeout = timeout

    def query(self, api_name: str, fields: str = "", **kwargs: Any) -> pd.DataFrame:
        patch_replay_dns()
        last_error = ""
        params = dict(kwargs)
        if fields:
            params["fields"] = fields

        for base_url in self.base_urls:
            session = build_session()
            url = f"{base_url}/{api_name}"
            try:
                response = session.get(url, headers={"X-API-Key": self.api_key}, params=params, timeout=self.timeout)
            except requests.exceptions.RequestException as exc:
                last_error = f"network_error(base_url={base_url}): {exc}"
                continue

            preview = response.text[:300].replace("\n", " ")
            if response.status_code == 530 and "cloudflare tunnel error" in response.text.lower():
                last_error = f"cloudflare_tunnel_unavailable(base_url={base_url})"
                continue
            if not response.ok:
                last_error = f"http_{response.status_code}(base_url={base_url}): {preview}"
                continue

            try:
                return payload_to_frame(response.json())
            except ValueError as exc:
                last_error = f"invalid_json(status={response.status_code}, base_url={base_url}): {exc}; preview={preview}"
                continue

        raise RuntimeError(last_error or f"{api_name} all_base_urls_failed")

    def __getattr__(self, name: str) -> Any:
        return partial(self.query, name)


class HttpPostDataApi:
    def __init__(self, token: str, url: str, timeout: int = 30) -> None:
        self.token = token
        self.url = url
        self.timeout = timeout

    def query(self, api_name: str, fields: str = "", **kwargs: Any) -> pd.DataFrame:
        session = build_session()
        payload = {
            "api_name": api_name,
            "token": self.token,
            "params": kwargs,
            "fields": fields,
        }
        response = session.post(
            self.url,
            json=payload,
            headers={"Accept-Encoding": "gzip"},
            timeout=self.timeout,
        )
        preview = response.text[:300].replace("\n", " ")
        if not response.ok:
            raise RuntimeError(f"http_{response.status_code}(url={self.url}): {preview}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"invalid_json(status={response.status_code}, url={self.url}): {exc}; preview={preview}") from exc
        if data.get("code") not in {0, None}:
            raise RuntimeError(f"tushare_code_{data.get('code')}: {data.get('msg') or preview}")
        return payload_to_frame(data)

    def __getattr__(self, name: str) -> Any:
        return partial(self.query, name)


def get_tushare_pro(root: str | os.PathLike[str] | None = None) -> Any:
    clear_bad_tushare_proxy()
    load_dotenv(root)

    token = token_value()
    http_url = http_url_value()
    if token and http_url:
        return HttpPostDataApi(token=token, url=http_url)

    api_key = replay_api_key()
    if api_key:
        return ReplayDataApi(api_key=api_key)

    if not token:
        raise RuntimeError("TUSHARE_TOKEN 和 TUSHARE_REPLAY_API_KEY 都不可见")

    import tushare as ts

    return ts.pro_api(token)
