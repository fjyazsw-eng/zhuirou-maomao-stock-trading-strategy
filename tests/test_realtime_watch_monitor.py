from __future__ import annotations

import tempfile
import unittest
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from scoring_system.cc_connect_notifier import DeliveryResult, discover_active_sessions, send_via_cc_connect
from scoring_system.eastmoney_intraday import IntradaySnapshot, MinuteBar, MoneyFlowPoint, aggregate_five_minute, secid_for_code
from scoring_system.realtime_watch_monitor import RealtimeWatchMonitor, build_message, decide_holding_state, decide_watch_state, trading_elapsed_fraction


def snapshot(code: str, price: float, pct: float = 0.5, amount_ratio: float = 1.0) -> IntradaySnapshot:
    start = datetime(2026, 7, 13, 9, 30)
    bars = tuple(
        MinuteBar(start + timedelta(minutes=i), price, price, price + 0.05, price - 0.05, 100, 10000, price)
        for i in range(15)
    )
    return IntradaySnapshot(code, code, code, bars[-1].timestamp, price, price / (1 + pct / 100), pct, price, price, price, 1500, 150000, amount_ratio, bars)


def snapshot_with_bars(code: str, bars: tuple[MinuteBar, ...], pct: float = 0.5, amount_ratio: float = 1.0) -> IntradaySnapshot:
    price = bars[-1].close
    return IntradaySnapshot(code, code, code, bars[-1].timestamp, price, price / (1 + pct / 100), pct, max(bar.high for bar in bars), min(bar.low for bar in bars), price, 1500, 150000, amount_ratio, bars)


def snapshot_at(code: str, price: float, trade_time: datetime, pct: float = 0.5, amount_ratio: float = 1.0) -> IntradaySnapshot:
    start = trade_time - timedelta(minutes=14)
    bars = tuple(
        MinuteBar(start + timedelta(minutes=i), price, price, price + 0.05, price - 0.05, 100, 10000, price)
        for i in range(15)
    )
    return IntradaySnapshot(code, code, code, trade_time, price, price / (1 + pct / 100), pct, price, price, price, 1500, 150000, amount_ratio, bars)


class RealtimeWatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.item = {
            "code": "600276.SH",
            "name": "恒瑞医药",
            "zone": {"low": 54.5, "high": 55.5},
            "rules": {},
        }
        self.now = datetime(2026, 7, 13, 9, 44)
        self.flows = [
            MoneyFlowPoint(datetime(2026, 7, 13, 9, 30) + timedelta(minutes=i), 1000000 + i * 10000, 0, 0, 0, 0)
            for i in range(15)
        ]

    def test_aggregate_five_minute_drops_incomplete_group(self) -> None:
        bars = list(snapshot("600276", 55.0).bars)[:12]
        grouped = aggregate_five_minute(bars)
        self.assertEqual(2, len(grouped))

    def test_tushare_code_is_converted_to_eastmoney_secid(self) -> None:
        self.assertEqual("1.600276", secid_for_code("600276.SH"))
        self.assertEqual("0.300759", secid_for_code("300759.SZ"))
        self.assertEqual("90.BK0465", secid_for_code("90.BK0465"))

    def test_trading_elapsed_fraction_handles_lunch_break(self) -> None:
        self.assertAlmostEqual(0.5, trading_elapsed_fraction(datetime(2026, 7, 13, 12, 0)))
        self.assertAlmostEqual(1.0, trading_elapsed_fraction(datetime(2026, 7, 13, 15, 0)))

    def test_confirmed_requires_price_volume_funds_and_sector(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 55.0),
            self.flows,
            snapshot("90.BK0465", 100.0, pct=0.3),
            [snapshot("600196", 10.0, pct=0.2)],
            [snapshot("1.000001", 3000.0, pct=0.1)],
            self.now,
        )
        self.assertEqual("CONFIRMED", decision.state)

    def test_price_hold_without_sector_confirmation_is_holding(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 55.0),
            self.flows,
            snapshot("90.BK0465", 100.0, pct=-2.0),
            [snapshot("600196", 10.0, pct=-3.0)],
            [snapshot("1.000001", 3000.0, pct=0.1)],
            self.now,
        )
        self.assertEqual("HOLDING", decision.state)
        self.assertFalse(decision.sector_ok)

    def test_stale_data_never_generates_price_signal(self) -> None:
        stale = snapshot("600276", 55.0)
        decision = decide_watch_state(self.item, stale, self.flows, None, [], [], datetime(2026, 7, 14, 10, 0))
        self.assertEqual("DATA_STALE", decision.state)

    def test_frozen_intraday_data_is_stale(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 55.0),
            self.flows,
            snapshot("90.BK0465", 100.0),
            [snapshot("600196", 10.0)],
            [snapshot("1.000001", 3000.0)],
            datetime(2026, 7, 13, 10, 0),
        )
        self.assertEqual("DATA_STALE", decision.state)

    def test_stale_money_flow_blocks_confirmation(self) -> None:
        stale_flows = [
            MoneyFlowPoint(point.timestamp - timedelta(days=1), point.main_net, 0, 0, 0, 0)
            for point in self.flows
        ]
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 55.0),
            stale_flows,
            snapshot("90.BK0465", 100.0),
            [snapshot("600196", 10.0)],
            [snapshot("1.000001", 3000.0)],
            self.now,
        )
        self.assertEqual("HOLDING", decision.state)
        self.assertFalse(decision.funds_ok)

    def test_below_zone_without_prior_touch_is_not_invalidated(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 53.0),
            self.flows,
            snapshot("90.BK0465", 100.0),
            [snapshot("600196", 10.0)],
            [snapshot("1.000001", 3000.0)],
            self.now,
        )
        self.assertEqual("BELOW_ZONE", decision.state)

    def test_holding_breaks_risk_line_only_after_two_minutes(self) -> None:
        item = {
            "code": "000988.SZ", "name": "测试持仓A", "quantity": 300, "cost": 10.0,
            "levels": {"support": 157.8, "risk": 153.5, "recovery": 161.3, "strength": 165.0},
            "rules": {},
        }
        decision = decide_holding_state(
            item,
            snapshot("000988", 153.0),
            self.flows,
            snapshot("90.BK0448", 100.0),
            [snapshot("300308", 10.0)],
            [snapshot("1.000001", 3000.0)],
            self.now,
        )
        self.assertEqual("RISK_ESCALATED", decision.state)
        self.assertEqual("holding", decision.kind)

    def test_holding_recovery_requires_two_five_minute_closes(self) -> None:
        item = {
            "code": "002281.SZ", "name": "测试持仓B", "quantity": 100, "cost": 20.0,
            "levels": {"support": 233.0, "risk": 229.0, "recovery": 238.5, "strength": 245.0},
            "rules": {},
        }
        decision = decide_holding_state(
            item,
            snapshot("002281", 240.0),
            self.flows,
            snapshot("90.BK0448", 100.0),
            [snapshot("300308", 10.0)],
            [snapshot("1.000001", 3000.0)],
            self.now,
        )
        self.assertEqual("RECOVERED", decision.state)

    def test_monitor_hot_reloads_confirmed_plan_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "watch.json"
            config_path.write_text('{"poll_interval_seconds":60,"watchlist":[]}', encoding="utf-8")
            monitor = RealtimeWatchMonitor(json.loads(config_path.read_text(encoding="utf-8")), config_path=config_path)
            config_path.write_text('{"poll_interval_seconds":30,"watchlist":[]}', encoding="utf-8")
            self.assertTrue(monitor.reload_config_if_changed())
            self.assertEqual(30, monitor.config["poll_interval_seconds"])

    def test_market_weakness_blocks_comprehensive_confirmation(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 55.0),
            self.flows,
            snapshot("90.BK0465", 100.0, pct=0.3),
            [snapshot("600196", 10.0, pct=0.2)],
            [snapshot("1.000001", 3000.0, pct=-2.0)],
            self.now,
        )
        self.assertEqual("HOLDING", decision.state)
        self.assertFalse(decision.market_ok)

    def test_above_zone_without_recent_touch_is_not_confirmed(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 56.0),
            self.flows,
            snapshot("90.BK0465", 100.0, pct=0.3),
            [snapshot("600196", 10.0, pct=0.2)],
            [snapshot("1.000001", 3000.0, pct=0.1)],
            self.now,
        )
        self.assertEqual("ABOVE_ZONE", decision.state)

    def test_above_zone_message_is_breakout_observation_not_chase(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 56.0),
            self.flows,
            snapshot("90.BK0465", 100.0, pct=0.3),
            [snapshot("600196", 10.0, pct=0.2)],
            [snapshot("1.000001", 3000.0, pct=0.1)],
            self.now,
        )
        message = build_message(decision)
        self.assertEqual("ABOVE_ZONE", decision.state)
        self.assertIn("突破观察，不追高，等二次买点", message)
        self.assertIn("原低吸计划未触发", message)

    def test_confirmed_message_uses_plain_action_and_ai_review_gate(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 55.0),
            self.flows,
            snapshot("90.BK0465", 100.0, pct=0.3),
            [snapshot("600196", 10.0, pct=0.2)],
            [snapshot("1.000001", 3000.0, pct=0.1)],
            self.now,
        )
        message = build_message(decision)
        self.assertEqual("CONFIRMED", decision.state)
        self.assertEqual(0, message.count("\n"))
        self.assertIn("恒瑞医药现价55.00", message)
        self.assertIn("已站稳观察条件", message)
        self.assertIn("建议可以考虑轻仓买入", message)
        self.assertIn("AI审核：需要", message)
        self.assertIn("如需审核请回复：审核 恒瑞医药 600276.SH 2026-07-13T09:44 确认轻仓买入", message)

    def test_breakout_retest_can_be_confirmed_after_prior_above_zone(self) -> None:
        start = datetime(2026, 7, 13, 9, 30)
        bars = tuple(
            MinuteBar(
                start + timedelta(minutes=i),
                55.9,
                55.8,
                56.0,
                55.45 if i >= 5 else 55.7,
                100,
                10000,
                55.8,
            )
            for i in range(15)
        )
        decision = decide_watch_state(
            self.item,
            snapshot_with_bars("600276", bars),
            self.flows,
            snapshot("90.BK0465", 100.0, pct=0.3),
            [snapshot("600196", 10.0, pct=0.2)],
            [snapshot("1.000001", 3000.0, pct=0.1)],
            self.now,
            previous_state="ABOVE_ZONE",
        )
        message = build_message(decision)
        self.assertEqual("CONFIRMED", decision.state)
        self.assertIn("已站稳观察条件", message)
        self.assertIn("AI审核：需要", message)

    def test_breakout_failure_below_zone_invalidates_prior_above_zone(self) -> None:
        decision = decide_watch_state(
            self.item,
            snapshot("600276", 53.0),
            self.flows,
            snapshot("90.BK0465", 100.0, pct=0.3),
            [snapshot("600196", 10.0, pct=0.2)],
            [snapshot("1.000001", 3000.0, pct=0.1)],
            self.now,
            previous_state="ABOVE_ZONE",
        )
        message = build_message(decision)
        self.assertEqual("INVALIDATED", decision.state)
        self.assertIn("原观察计划失效", message)

    def test_risk_escalated_message_uses_plain_reduce_or_sell_guidance(self) -> None:
        item = {
            "code": "000988.SZ", "name": "测试持仓A", "quantity": 300, "cost": 10.0,
            "levels": {"support": 157.8, "risk": 153.5, "recovery": 161.3, "strength": 165.0},
            "rules": {},
        }
        decision = decide_holding_state(
            item,
            snapshot("000988", 153.0),
            self.flows,
            snapshot("90.BK0448", 100.0),
            [snapshot("300308", 10.0)],
            [snapshot("1.000001", 3000.0)],
            self.now,
        )
        message = build_message(decision)
        self.assertEqual("RISK_ESCALATED", decision.state)
        self.assertEqual(0, message.count("\n"))
        self.assertIn("测试持仓A现价153.00", message)
        self.assertIn("已跌破风险线", message)
        self.assertIn("建议卖出一部分做止损风控", message)
        self.assertIn("AI审核：需要", message)
        self.assertIn("如需审核请回复：审核 测试持仓A 000988.SZ 2026-07-13T09:44 跌破风险线", message)

    def test_cc_connect_discovers_latest_active_session_per_platform(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sessions").mkdir()
            (root / "sessions" / "codex-weixin_abcd.json").write_text(
                '{"active_session":{"weixin:dm:user":"s1","feishu:chat:user":"s2"},'
                '"sessions":{"s1":{"updated_at":"2026-07-11T10:00:00"},"s2":{"updated_at":"2026-07-11T11:00:00"}}}',
                encoding="utf-8",
            )
            result = discover_active_sessions(root, "codex-weixin", ["weixin", "feishu"])
            self.assertEqual({"weixin": "weixin:dm:user", "feishu": "feishu:chat:user"}, result)

    def test_cc_connect_send_uses_same_custom_data_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sessions").mkdir()
            (root / "sessions" / "codex-weixin_abcd.json").write_text(
                '{"active_session":{"weixin:dm:user":"s1"},"sessions":{"s1":{"updated_at":"2026-07-11T10:00:00"}}}',
                encoding="utf-8",
            )
            with patch("scoring_system.cc_connect_notifier.shutil.which", return_value="cc-connect.exe"), patch(
                "scoring_system.cc_connect_notifier.subprocess.run"
            ) as runner:
                runner.return_value.returncode = 0
                runner.return_value.stdout = "ok"
                runner.return_value.stderr = ""
                send_via_cc_connect("test", platforms=["weixin"], data_dir=root)
                command = runner.call_args.args[0]
                self.assertEqual(str(root), command[command.index("--data-dir") + 1])

    def test_cc_connect_send_can_pin_feishu_group_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sessions").mkdir()
            (root / "sessions" / "codex-weixin_abcd.json").write_text(
                '{"active_session":{"feishu:wrong_group:user":"s1","feishu:pinned_group:user":"s2"},'
                '"sessions":{"s1":{"updated_at":"2026-07-13T10:47:00"},"s2":{"updated_at":"2026-07-13T09:49:00"}}}',
                encoding="utf-8",
            )
            with patch("scoring_system.cc_connect_notifier.shutil.which", return_value="cc-connect.exe"), patch(
                "scoring_system.cc_connect_notifier.subprocess.run"
            ) as runner:
                runner.return_value.returncode = 0
                runner.return_value.stdout = "ok"
                runner.return_value.stderr = ""
                send_via_cc_connect(
                    "test",
                    platforms=["feishu"],
                    data_dir=root,
                    session_overrides={"feishu": "feishu:pinned_group:user"},
                )
                command = runner.call_args.args[0]
                self.assertEqual("feishu:pinned_group:user", command[command.index("-s") + 1])

    def test_cc_connect_preserves_first_success_when_second_platform_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sessions").mkdir()
            (root / "sessions" / "codex-weixin_abcd.json").write_text(
                '{"active_session":{"weixin:dm:user":"s1","feishu:chat:user":"s2"},'
                '"sessions":{"s1":{"updated_at":"2026-07-11T10:00:00"},"s2":{"updated_at":"2026-07-11T10:00:00"}}}',
                encoding="utf-8",
            )
            success = unittest.mock.Mock(returncode=0, stdout="ok", stderr="")
            with patch("scoring_system.cc_connect_notifier.shutil.which", return_value="cc-connect.exe"), patch(
                "scoring_system.cc_connect_notifier.subprocess.run",
                side_effect=[success, __import__("subprocess").TimeoutExpired("cc-connect", 30)],
            ):
                results = send_via_cc_connect("test", data_dir=root)
                self.assertTrue(results[0].sent)
                self.assertFalse(results[1].sent)

    def test_failed_platform_delivery_is_retried_without_resending_success(self) -> None:
        config = {
            "market": {"references": ["1.000001"]},
            "cc_connect": {"project": "codex-weixin", "platforms": ["weixin", "feishu"]},
            "notification": {"states": ["CONFIRMED"]},
            "watchlist": [{**self.item, "sector": {"secid": "90.BK0465", "references": ["600196.SH"]}}],
        }

        def fetcher(code: str, ndays: int) -> IntradaySnapshot:
            prices = {"600276.SH": 55.0, "90.BK0465": 100.0, "600196.SH": 10.0, "1.000001": 3000.0}
            return snapshot(code, prices[code])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_file = root / "state.json"
            report_file = root / "latest.json"
            monitor = RealtimeWatchMonitor(config, fetcher, lambda code, limit: self.flows, lambda code, value: 100000)
            with patch("scoring_system.realtime_watch_monitor.STATE_FILE", state_file), patch(
                "scoring_system.realtime_watch_monitor.LATEST_REPORT", report_file
            ), patch("scoring_system.realtime_watch_monitor.send_via_cc_connect") as sender:
                sender.return_value = [
                    DeliveryResult("weixin", "w", True, "ok"),
                    DeliveryResult("feishu", "f", False, "temporary failure"),
                ]
                monitor.run_once(now=self.now, send=True)
                saved = json.loads(state_file.read_text(encoding="utf-8"))["600276.SH"]
                self.assertEqual("CONFIRMED", saved["platform_states"]["weixin"])
                self.assertNotIn("feishu", saved["platform_states"])

                sender.return_value = [DeliveryResult("feishu", "f", True, "ok")]
                monitor.run_once(now=self.now, send=True)
                self.assertEqual(["feishu"], sender.call_args.kwargs["platforms"])

    def test_monitor_forwards_pinned_cc_connect_sessions(self) -> None:
        config = {
            "market": {"references": ["1.000001"]},
            "cc_connect": {
                "project": "codex-weixin",
                "platforms": ["weixin", "feishu"],
                "session_overrides": {"feishu": "feishu:pinned_group:user"},
            },
            "notification": {"states": ["CONFIRMED"]},
            "watchlist": [{**self.item, "sector": {"secid": "90.BK0465", "references": ["600196.SH"]}}],
        }

        def fetcher(code: str, ndays: int) -> IntradaySnapshot:
            prices = {"600276.SH": 55.0, "90.BK0465": 100.0, "600196.SH": 10.0, "1.000001": 3000.0}
            return snapshot(code, prices[code])

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            report_file = Path(tmp) / "latest.json"
            monitor = RealtimeWatchMonitor(config, fetcher, lambda code, limit: self.flows, lambda code, value: 100000)
            with patch("scoring_system.realtime_watch_monitor.STATE_FILE", state_file), patch(
                "scoring_system.realtime_watch_monitor.LATEST_REPORT", report_file
            ), patch("scoring_system.realtime_watch_monitor.send_via_cc_connect") as sender:
                sender.return_value = [DeliveryResult("feishu", "f", True, "ok")]
                monitor.run_once(now=self.now, send=True)
                self.assertEqual({"feishu": "feishu:pinned_group:user"}, sender.call_args.kwargs["session_overrides"])

    def test_same_state_is_not_deduplicated_across_trade_dates(self) -> None:
        config = {
            "market": {"references": ["1.000001"]},
            "cc_connect": {"project": "codex-weixin", "platforms": ["weixin", "feishu"]},
            "notification": {"states": ["CONFIRMED"]},
            "watchlist": [{**self.item, "sector": {"secid": "90.BK0465", "references": ["600196.SH"]}}],
        }

        def fetcher(code: str, ndays: int) -> IntradaySnapshot:
            prices = {"600276.SH": 55.0, "90.BK0465": 100.0, "600196.SH": 10.0, "1.000001": 3000.0}
            return snapshot(code, prices[code])

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            report_file = Path(tmp) / "latest.json"
            state_file.write_text(
                json.dumps({"600276.SH": {"state": "CONFIRMED", "trade_date": "2026-07-10", "platform_states": {"weixin": "CONFIRMED", "feishu": "CONFIRMED"}}}),
                encoding="utf-8",
            )
            monitor = RealtimeWatchMonitor(config, fetcher, lambda code, limit: self.flows, lambda code, value: 100000)
            with patch("scoring_system.realtime_watch_monitor.STATE_FILE", state_file), patch(
                "scoring_system.realtime_watch_monitor.LATEST_REPORT", report_file
            ), patch("scoring_system.realtime_watch_monitor.send_via_cc_connect") as sender:
                sender.return_value = [
                    DeliveryResult("weixin", "w", True, "ok"),
                    DeliveryResult("feishu", "f", True, "ok"),
                ]
                monitor.run_once(now=self.now, send=True)
                self.assertEqual(["weixin", "feishu"], sender.call_args.kwargs["platforms"])

    def test_same_notification_state_sends_again_after_cooldown(self) -> None:
        config = {
            "market": {"references": ["1.000001"]},
            "cc_connect": {"project": "codex-weixin", "platforms": ["weixin", "feishu"]},
            "notification": {"states": ["CONFIRMED"]},
            "watchlist": [{**self.item, "sector": {"secid": "90.BK0465", "references": ["600196.SH"]}}],
        }
        current_price = {"value": 55.0}
        current_time = {"value": self.now}

        def fetcher(code: str, ndays: int) -> IntradaySnapshot:
            prices = {"600276.SH": current_price["value"], "90.BK0465": 100.0, "600196.SH": 10.0, "1.000001": 3000.0}
            return snapshot_at(code, prices[code], current_time["value"])

        def flow_fetcher(code: str, limit: int) -> list[MoneyFlowPoint]:
            start = current_time["value"] - timedelta(minutes=14)
            return [
                MoneyFlowPoint(start + timedelta(minutes=i), 1000000 + i * 10000, 0, 0, 0, 0)
                for i in range(15)
            ]

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            report_file = Path(tmp) / "latest.json"
            monitor = RealtimeWatchMonitor(config, fetcher, flow_fetcher, lambda code, value: 100000)
            with patch("scoring_system.realtime_watch_monitor.STATE_FILE", state_file), patch(
                "scoring_system.realtime_watch_monitor.LATEST_REPORT", report_file
            ), patch("scoring_system.realtime_watch_monitor.send_via_cc_connect") as sender:
                sender.return_value = [DeliveryResult("weixin", "w", True, "ok"), DeliveryResult("feishu", "f", True, "ok")]
                monitor.run_once(now=self.now, send=True)
                current_time["value"] = self.now + timedelta(minutes=61)
                monitor.run_once(now=current_time["value"], send=True)
                self.assertEqual(2, sender.call_count)

    def test_notification_cooldown_blocks_same_stock_repeat_within_sixty_minutes(self) -> None:
        config = {
            "market": {"references": ["1.000001"]},
            "cc_connect": {"project": "codex-weixin", "platforms": ["weixin", "feishu"]},
            "notification": {"states": ["CONFIRMED", "INVALIDATED"], "min_interval_minutes": 60},
            "watchlist": [{**self.item, "sector": {"secid": "90.BK0465", "references": ["600196.SH"]}}],
        }
        current_price = {"value": 55.0}
        current_time = {"value": self.now}

        def fetcher(code: str, ndays: int) -> IntradaySnapshot:
            prices = {"600276.SH": current_price["value"], "90.BK0465": 100.0, "600196.SH": 10.0, "1.000001": 3000.0}
            return snapshot_at(code, prices[code], current_time["value"])

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            report_file = Path(tmp) / "latest.json"
            monitor = RealtimeWatchMonitor(config, fetcher, lambda code, limit: self.flows, lambda code, value: 100000)
            with patch("scoring_system.realtime_watch_monitor.STATE_FILE", state_file), patch(
                "scoring_system.realtime_watch_monitor.LATEST_REPORT", report_file
            ), patch("scoring_system.realtime_watch_monitor.send_via_cc_connect") as sender:
                sender.return_value = [DeliveryResult("weixin", "w", True, "ok"), DeliveryResult("feishu", "f", True, "ok")]
                monitor.run_once(now=self.now, send=True)
                current_price["value"] = 53.0
                current_time["value"] = self.now + timedelta(minutes=30)
                monitor.run_once(now=current_time["value"], send=True)
                self.assertEqual(1, sender.call_count)

    def test_notification_cooldown_allows_same_stock_repeat_after_sixty_minutes(self) -> None:
        config = {
            "market": {"references": ["1.000001"]},
            "cc_connect": {"project": "codex-weixin", "platforms": ["weixin", "feishu"]},
            "notification": {"states": ["CONFIRMED", "INVALIDATED"], "min_interval_minutes": 60},
            "watchlist": [{**self.item, "sector": {"secid": "90.BK0465", "references": ["600196.SH"]}}],
        }
        current_price = {"value": 55.0}
        current_time = {"value": self.now}

        def fetcher(code: str, ndays: int) -> IntradaySnapshot:
            prices = {"600276.SH": current_price["value"], "90.BK0465": 100.0, "600196.SH": 10.0, "1.000001": 3000.0}
            return snapshot_at(code, prices[code], current_time["value"])

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            report_file = Path(tmp) / "latest.json"
            monitor = RealtimeWatchMonitor(config, fetcher, lambda code, limit: self.flows, lambda code, value: 100000)
            with patch("scoring_system.realtime_watch_monitor.STATE_FILE", state_file), patch(
                "scoring_system.realtime_watch_monitor.LATEST_REPORT", report_file
            ), patch("scoring_system.realtime_watch_monitor.send_via_cc_connect") as sender:
                sender.return_value = [DeliveryResult("weixin", "w", True, "ok"), DeliveryResult("feishu", "f", True, "ok")]
                monitor.run_once(now=self.now, send=True)
                current_price["value"] = 53.0
                current_time["value"] = self.now + timedelta(minutes=61)
                monitor.run_once(now=current_time["value"], send=True)
                self.assertEqual(2, sender.call_count)

    def test_candidate_notifications_only_include_actionable_confirmation_or_invalidated_plan(self) -> None:
        config = {
            "market": {"references": ["1.000001"]},
            "cc_connect": {"project": "codex-weixin", "platforms": ["weixin", "feishu"]},
            "notification": {
                "candidate_states": ["CONFIRMED", "INVALIDATED"],
                "holding_states": ["RECOVERY_REJECTED", "SUPPORT_BROKEN", "RISK_ESCALATED"],
                "states": ["ABOVE_ZONE", "CONFIRMED"],
            },
            "watchlist": [{**self.item, "sector": {"secid": "90.BK0465", "references": ["600196.SH"]}}],
        }

        def fetcher(code: str, ndays: int) -> IntradaySnapshot:
            prices = {"600276.SH": 56.0, "90.BK0465": 100.0, "600196.SH": 10.0, "1.000001": 3000.0}
            return snapshot(code, prices[code])

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            report_file = Path(tmp) / "latest.json"
            monitor = RealtimeWatchMonitor(config, fetcher, lambda code, limit: self.flows, lambda code, value: 100000)
            with patch("scoring_system.realtime_watch_monitor.STATE_FILE", state_file), patch(
                "scoring_system.realtime_watch_monitor.LATEST_REPORT", report_file
            ), patch("scoring_system.realtime_watch_monitor.send_via_cc_connect") as sender:
                monitor.run_once(now=self.now, send=True)
                self.assertEqual(0, sender.call_count)

    def test_holding_notifications_exclude_recovered_and_strengthened_states(self) -> None:
        holding = {
            "code": "002281.SZ",
            "name": "测试持仓B",
            "quantity": 100,
            "cost": 20.0,
            "levels": {"support": 233.0, "risk": 229.0, "recovery": 238.5, "strength": 245.0},
            "rules": {},
            "sector": {"secid": "90.BK0448", "references": ["300308.SZ"]},
        }
        config = {
            "market": {"references": ["1.000001"]},
            "cc_connect": {"project": "codex-weixin", "platforms": ["weixin", "feishu"]},
            "notification": {
                "candidate_states": ["CONFIRMED", "INVALIDATED"],
                "holding_states": ["RECOVERY_REJECTED", "SUPPORT_BROKEN", "RISK_ESCALATED"],
                "states": ["RECOVERED", "STRENGTH_CONFIRMED", "RISK_ESCALATED"],
            },
            "watchlist": [],
            "holding_watchlist": [holding],
        }

        def fetcher(code: str, ndays: int) -> IntradaySnapshot:
            prices = {"002281.SZ": 240.0, "90.BK0448": 100.0, "300308.SZ": 10.0, "1.000001": 3000.0}
            return snapshot(code, prices[code])

        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "state.json"
            report_file = Path(tmp) / "latest.json"
            monitor = RealtimeWatchMonitor(config, fetcher, lambda code, limit: self.flows, lambda code, value: 100000)
            with patch("scoring_system.realtime_watch_monitor.STATE_FILE", state_file), patch(
                "scoring_system.realtime_watch_monitor.LATEST_REPORT", report_file
            ), patch("scoring_system.realtime_watch_monitor.send_via_cc_connect") as sender:
                report = monitor.run_once(now=self.now, send=True)
                self.assertEqual("RECOVERED", report["decisions"][0]["state"])
                self.assertEqual(0, sender.call_count)


if __name__ == "__main__":
    unittest.main()
