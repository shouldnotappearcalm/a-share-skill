#!/usr/bin/env python3
"""Batch backtest validation across real A-share symbols."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from paper_trading.engine import PaperTradingEngine  # noqa: E402
from paper_trading.market_data import MarketDataProvider  # noqa: E402


SYMBOLS = [
    "600519",
    "601318",
    "600036",
    "600276",
    "000858",
    "000333",
    "002594",
    "601398",
    "300750",
    "300059",
    "300308",
    "300274",
    "300124",
    "300760",
    "688981",
    "688041",
    "688111",
    "688256",
    "600309",
    "002475",
]


def _assert(expr: bool, message: str) -> None:
    if not expr:
        raise AssertionError(message)


def main() -> None:
    provider = MarketDataProvider()
    for round_idx in range(1, 4):
        with tempfile.TemporaryDirectory() as tmp:
            engine = PaperTradingEngine(str(Path(tmp) / f"backtest_{round_idx}.db"), market_data=provider)
            for symbol in SYMBOLS:
                result = engine.run_backtest(
                    symbol=symbol,
                    strategy="sma_cross",
                    start="2025-01-01",
                    end="2026-03-31",
                    initial_cash=200000.0,
                    params={"fast": 5, "slow": 20},
                )
                _assert(result["symbol"] == symbol, f"{symbol} symbol mismatch")
                _assert(result["initial_capital"] == 200000.0, f"{symbol} initial capital mismatch")
                _assert(result["final_capital"] > 0, f"{symbol} final capital invalid")
                _assert(isinstance(result["trades"], list), f"{symbol} trades not list")
                _assert(isinstance(result["equity_curve"], list) and len(result["equity_curve"]) > 0, f"{symbol} missing equity curve")
        print(f"round {round_idx} ok for {len(SYMBOLS)} backtests")
    print("PASS backtest_batch_validation", SYMBOLS)


if __name__ == "__main__":
    main()
