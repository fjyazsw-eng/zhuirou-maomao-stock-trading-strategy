from __future__ import annotations

import unittest

from scoring_system.tushare_client import should_use_env_proxy_for_url


class RetiredProviderProxyTests(unittest.TestCase):
    def test_legacy_provider_urls_are_not_special_cased(self) -> None:
        self.assertTrue(should_use_env_proxy_for_url("https://ts.gyzcloud.top/api"))
        self.assertTrue(should_use_env_proxy_for_url("https://ts2.gyzcloud.top/api"))
        self.assertTrue(should_use_env_proxy_for_url("https://api.waditu.com"))
        self.assertTrue(should_use_env_proxy_for_url("https://ai-tool.indevs.in/tushare/pro/stock_basic"))

    def test_hithink_endpoint_can_use_normal_environment_proxy(self) -> None:
        self.assertTrue(should_use_env_proxy_for_url("https://fuyao.aicubes.cn/api/a-share/prices/snapshot"))


if __name__ == "__main__":
    unittest.main()
