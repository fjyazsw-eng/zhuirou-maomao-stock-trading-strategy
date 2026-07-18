"""Unit conversion helpers for market data.

Tushare daily.amount is reported in thousand CNY. Keep volume (vol) conversions
separate; these helpers only convert monetary amount fields.
"""

from __future__ import annotations


def tushare_amount_to_yi(amount_qianyuan: float | int) -> float:
    """Convert Tushare daily amount from thousand CNY to 100 million CNY."""
    return float(amount_qianyuan) / 100000


def tushare_amount_to_wanyi(amount_qianyuan: float | int) -> float:
    """Convert Tushare daily amount from thousand CNY to trillion CNY."""
    return float(amount_qianyuan) / 1000000000
