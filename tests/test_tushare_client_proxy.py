from __future__ import annotations

import unittest

from scoring_system.tushare_client import should_use_env_proxy_for_url


class TushareClientProxyTests(unittest.TestCase):
    def test_tushare_endpoints_ignore_env_proxy(self) -> None:
        self.assertFalse(should_use_env_proxy_for_url("https://ts.gyzcloud.top/api"))
        self.assertFalse(should_use_env_proxy_for_url("https://ts2.gyzcloud.top/api"))
        self.assertFalse(should_use_env_proxy_for_url("https://api.waditu.com"))
        self.assertFalse(should_use_env_proxy_for_url("https://ai-tool.indevs.in/tushare/pro/stock_basic"))

    def test_official_tushare_endpoint_keeps_existing_no_proxy_path(self) -> None:
        self.assertFalse(should_use_env_proxy_for_url("https://api.waditu.com"))


if __name__ == "__main__":
    unittest.main()
