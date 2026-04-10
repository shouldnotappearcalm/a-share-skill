#!/usr/bin/env python3
"""Offline smoke checks for core paper trading functionality."""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import paper_trading.engine as engine_module  # noqa: E402
from paper_trading.engine import OrderRequest, PaperTradingEngine  # noqa: E402
from paper_trading.market_data import Quote  # noqa: E402


class FakeMarketData:
    def __init__(self) -> None:
        self.quote = Quote(
            symbol="600519",
            name="贵州茅台",
            price=1450.0,
            open=1448.0,
            high=1452.0,
            low=1446.0,
            prev_close=1440.0,
            volume=100000,
            change_pct=0.69,
            timestamp="2026-04-11 10:00:00",
            source="fake",
            limit_up=1584.0,
            limit_down=1296.0,
        )

    def normalize_symbol(self, symbol: str) -> str:
        return symbol

    def get_quote(self, symbol: str) -> Quote:
        return self.quote

    def get_quotes(self, symbols):
        return {symbol: self.quote for symbol in symbols}

    def get_intraday_bars(self, symbol: str, freq: str = "1m", count: int = 240):
        return pd.DataFrame(
            [
                {"time": pd.Timestamp("2026-04-11 09:59:00"), "open": 1448.0, "high": 1450.0, "low": 1447.5, "close": 1449.8, "volume": 1000},
                {"time": pd.Timestamp("2026-04-11 10:00:00"), "open": 1449.5, "high": 1451.0, "low": 1448.5, "close": 1450.0, "volume": 1200},
            ]
        )

    def get_history(self, symbol: str, start: str | None = None, end: str | None = None, count: int = 240):
        dates = pd.date_range("2025-01-01", periods=120, freq="B")
        return pd.DataFrame(
            {
                "time": dates,
                "open": [100 + i * 0.1 for i in range(len(dates))],
                "high": [101 + i * 0.1 for i in range(len(dates))],
                "low": [99 + i * 0.1 for i in range(len(dates))],
                "close": [100 + i * 0.15 for i in range(len(dates))],
                "volume": [100000 + i * 10 for i in range(len(dates))],
            }
        ).tail(count).reset_index(drop=True)


def _assert(expr: bool, message: str) -> None:
    if not expr:
        raise AssertionError(message)


def _assert_raises(fn, contains: str) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        if contains not in str(exc):
            raise AssertionError(f"expected {contains!r}, got {exc!r}") from exc
        return
    raise AssertionError(f"expected exception containing {contains!r}")


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def run_engine_checks() -> None:
    fake_data = FakeMarketData()
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "smoke.db")
        engine = PaperTradingEngine(db_path, market_data=fake_data)
        acct = engine.create_account("alpha", 500000)
        _assert(acct["cash"] == 500000.0, "create_account cash mismatch")
        _assert(engine.get_default_account_id() == "alpha", "default account mismatch")
        engine.adjust_cash("alpha", 10000, "deposit")
        _assert(engine.get_account("alpha")["cash"] == 510000.0, "add cash failed")
        engine.adjust_cash("alpha", -5000, "withdraw")
        _assert(engine.get_account("alpha")["cash"] == 505000.0, "deduct cash failed")
        _assert_raises(
            lambda: engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="limit", limit_price=1450.005)),
            "0.01",
        )
        buy_limit = engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="limit", limit_price=1449.5))
        _assert(buy_limit["status"] == "open", "limit order not open")
        frozen = engine.get_account("alpha")["frozen_cash"]
        _assert(frozen > 0, "frozen cash not reserved")
        engine.cancel_order(buy_limit["order_id"])
        _assert(engine.get_account("alpha")["frozen_cash"] == 0.0, "cancel did not release frozen cash")

        original_is_trading_time = engine_module.is_trading_time
        original_trade_date = engine_module.trade_date
        original_is_after_close = engine_module.is_after_close
        try:
            engine_module.is_trading_time = lambda dt=None: True
            engine_module.trade_date = lambda: "2026-04-11"
            market_buy = engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="market"))
            _assert(market_buy["status"] == "filled", "market buy not filled")
            positions = engine.get_positions("alpha")
            _assert(len(positions) == 1 and positions[0]["qty"] == 100, "position not created")
            _assert_raises(
                lambda: engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="sell", qty=100, order_type="limit", limit_price=1450.0)),
                "insufficient sellable qty",
            )
            with sqlite3.connect(db_path) as conn:
                conn.execute("UPDATE position_lots SET acquired_date = '2026-04-10' WHERE account_id = 'alpha'")
                conn.commit()
            sell_order = engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="sell", qty=100, order_type="limit", limit_price=1450.0))
            processed = engine.process_orders()
            _assert(processed["filled"] >= 1, "sell order not processed")
            _assert(engine.get_order(sell_order["order_id"])["status"] == "filled", "sell order not filled")
            snapshots = engine.snapshot_accounts()
            _assert(snapshots["snapshots"] >= 1, "snapshot missing")
            reset = engine.reset_account("alpha", 300000)
            _assert(reset["cash"] == 300000.0 and reset["order_count"] == 0, "reset failed")

            pending = engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="limit", limit_price=1400.0))
            engine_module.is_trading_time = lambda dt=None: False
            engine_module.is_after_close = lambda dt=None: True
            expired = engine.expire_day_orders()
            _assert(expired == 1, "expire_day_orders count mismatch")
            _assert(engine.get_order(pending["order_id"])["status"] == "expired", "order not expired")
        finally:
            engine_module.is_trading_time = original_is_trading_time
            engine_module.trade_date = original_trade_date
            engine_module.is_after_close = original_is_after_close


def run_service_cli_checks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = str(Path(tmp) / "service.db")
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        service_cmd = [
            sys.executable,
            str(SCRIPT_DIR / "paper_trading_service.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--db-path",
            db_path,
            "--match-interval",
            "1",
            "--valuation-interval",
            "1",
            "--idle-valuation-interval",
            "1",
        ]
        proc = subprocess.Popen(service_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.time() + 15
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(f"{base}/health", timeout=2) as resp:
                        body = json.loads(resp.read().decode("utf-8"))
                        if body.get("status") == "ok":
                            break
                except Exception:
                    time.sleep(0.2)
            else:
                raise AssertionError("service did not start")

            cli = [sys.executable, str(SCRIPT_DIR / "paper_trade_cli.py"), "--base-url", base]
            subprocess.run(cli + ["create-account", "svc", "--cash", "200000"], check=True, capture_output=True, text=True)
            subprocess.run(cli + ["set-default-account", "svc"], check=True, capture_output=True, text=True)
            default_out = subprocess.run(cli + ["show-default-account"], check=True, capture_output=True, text=True).stdout
            _assert("svc" in default_out, "default account CLI failed")
            subprocess.run(cli + ["add-cash", "svc", "10000"], check=True, capture_output=True, text=True)
            account_out = subprocess.run(cli + ["show-account", "svc"], check=True, capture_output=True, text=True).stdout
            _assert("210000" in account_out.replace(",", ""), "show-account CLI failed")
            list_out = subprocess.run(cli + ["list-accounts"], check=True, capture_output=True, text=True).stdout
            _assert("svc" in list_out, "list-accounts CLI failed")
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


def main() -> None:
    run_engine_checks()
    run_service_cli_checks()
    print("PASS full_function_smoke_check")


if __name__ == "__main__":
    main()
