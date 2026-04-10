#!/usr/bin/env python3
"""Validate A-share board limit rules against real stocks."""

from __future__ import annotations

import tempfile
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from paper_trading.engine import OrderRequest, PaperTradingEngine  # noqa: E402
from paper_trading.market_data import MarketDataProvider, infer_limit_ratio  # noqa: E402


SAMPLES = [
    {"symbol": "600519", "bucket": "main"},
    {"symbol": "601318", "bucket": "main"},
    {"symbol": "600036", "bucket": "main"},
    {"symbol": "600276", "bucket": "main"},
    {"symbol": "000858", "bucket": "main"},
    {"symbol": "000333", "bucket": "main"},
    {"symbol": "002594", "bucket": "main"},
    {"symbol": "601398", "bucket": "main"},
    {"symbol": "300750", "bucket": "chinext"},
    {"symbol": "300059", "bucket": "chinext"},
    {"symbol": "300308", "bucket": "chinext"},
    {"symbol": "300274", "bucket": "chinext"},
    {"symbol": "300124", "bucket": "chinext"},
    {"symbol": "300760", "bucket": "chinext"},
    {"symbol": "688981", "bucket": "star"},
    {"symbol": "688041", "bucket": "star"},
    {"symbol": "688111", "bucket": "star"},
    {"symbol": "688256", "bucket": "star"},
    {"symbol": "300561", "bucket": "st"},
    {"symbol": "300555", "bucket": "st"},
    {"symbol": "300506", "bucket": "st"},
    {"symbol": "600243", "bucket": "st"},
]


def _assert_limit_ratio_ok(quote) -> None:
    expected = infer_limit_ratio(quote.symbol, quote.name)
    if quote.limit_up is None or quote.limit_down is None or quote.prev_close <= 0:
        raise AssertionError(f"{quote.symbol} missing limit prices")
    actual_up = (float(quote.limit_up) - float(quote.prev_close)) / float(quote.prev_close)
    actual_down = (float(quote.prev_close) - float(quote.limit_down)) / float(quote.prev_close)
    tolerance = 0.011
    if abs(actual_up - expected) > tolerance or abs(actual_down - expected) > tolerance:
        raise AssertionError(
            f"{quote.symbol} {quote.name} expected ratio {expected:.3f}, got up={actual_up:.4f}, down={actual_down:.4f}"
        )


def _assert_rejects_outside_limits(engine: PaperTradingEngine, symbol: str, quote) -> None:
    account_id = "verify"
    upper_bad = round(float(quote.limit_up) + 0.01, 2)
    lower_bad = round(float(quote.limit_down) - 0.01, 2)
    cases = [
        (upper_bad, "above daily limit up"),
        (lower_bad, "below daily limit down"),
    ]
    for bad_price, expected_text in cases:
        try:
            engine.place_order(OrderRequest(account_id=account_id, symbol=symbol, side="buy", qty=100, order_type="limit", limit_price=bad_price))
        except Exception as exc:  # noqa: BLE001
            if expected_text not in str(exc):
                raise AssertionError(f"{symbol} expected {expected_text!r}, got {exc!r}") from exc
        else:
            raise AssertionError(f"{symbol} unexpectedly accepted invalid price {bad_price}")


def main() -> None:
    provider = MarketDataProvider()
    for round_idx in range(1, 4):
        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperTradingEngine(str(Path(tmp) / f"validation_{round_idx}.db"), market_data=provider)
            engine.create_account("verify", 100000000.0)
            for sample in SAMPLES:
                quote = provider.get_quote(sample["symbol"])
                _assert_limit_ratio_ok(quote)
                _assert_rejects_outside_limits(engine, sample["symbol"], quote)
        print(f"round {round_idx} ok for {len(SAMPLES)} stocks")
    print("PASS real_stock_rule_validation", [sample["symbol"] for sample in SAMPLES])


if __name__ == "__main__":
    main()
