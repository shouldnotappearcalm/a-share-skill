#!/usr/bin/env python3
"""Non-market smoke tests for the paper trading skill."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import paper_trading.engine as eng
from paper_trading.engine import OrderRequest, PaperTradingEngine


def assert_true(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed: {detail}")
    print(f"PASS {name}")


def main() -> None:
    db_path = Path(__file__).resolve().parent.parent / "cache" / "paper_trading_non_market_test.db"
    db_path.unlink(missing_ok=True)
    engine = PaperTradingEngine(str(db_path))

    account = engine.create_account("alpha", 500000)
    assert_true("create_account_cash", account["cash"] == 500000.0, str(account))
    assert_true("create_account_net_asset", account["net_asset"] == 500000.0, str(account))
    assert_true("default_account_set", engine.get_default_account_id() == "alpha", engine.get_default_account_id() or "")

    adjusted = engine.adjust_cash("alpha", 1000, "deposit")
    assert_true("add_cash", abs(adjusted["cash"] - 501000.0) < 1e-6, str(adjusted))
    adjusted = engine.adjust_cash("alpha", -500, "withdraw")
    assert_true("deduct_cash", abs(adjusted["cash"] - 500500.0) < 1e-6, str(adjusted))

    order = engine.place_order(
        OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="limit", limit_price=1400)
    )
    account = engine.get_account("alpha")
    expected_reserved = 140000 + max(5.0, round(140000 * 0.0003, 2))
    expected_cash = 500500.0
    assert_true("freeze_cash", abs(account["frozen_cash"] - expected_reserved) < 1e-6, str(account))
    assert_true("available_cash", abs(account["available_cash"] - (expected_cash - expected_reserved)) < 1e-6, str(account))

    cancelled = engine.cancel_order(order["order_id"])
    account = engine.get_account("alpha")
    assert_true("cancel_status", cancelled["status"] == "cancelled", str(cancelled))
    assert_true("cancel_release", account["frozen_cash"] == 0.0, str(account))

    try:
        engine.place_order(OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="market"))
    except Exception as exc:
        assert_true("market_offhours_reject", "only accepted during trading hours" in str(exc), str(exc))
    else:
        raise AssertionError("market_offhours_reject failed: market order accepted off-hours")

    order = engine.place_order(
        OrderRequest(account_id="alpha", symbol="600519", side="buy", qty=100, order_type="limit", limit_price=1400)
    )
    original_is_after_close = eng.is_after_close
    eng.is_after_close = lambda dt=None: True
    try:
        expired = engine.expire_day_orders()
    finally:
        eng.is_after_close = original_is_after_close
    account = engine.get_account("alpha")
    order = engine.get_order(order["order_id"])
    assert_true("expire_count", expired >= 1, str(expired))
    assert_true("expire_status", order["status"] == "expired", str(order))
    assert_true("expire_release", account["frozen_cash"] == 0.0, str(account))

    engine.snapshot_accounts()
    conn = sqlite3.connect(str(db_path))
    snapshot_count = conn.execute("select count(*) from account_snapshots").fetchone()[0]
    assert_true("snapshot_written", snapshot_count >= 1, str(snapshot_count))

    reloaded = PaperTradingEngine(str(db_path))
    reloaded_account = reloaded.get_account("alpha")
    assert_true("restart_persist_cash", reloaded_account["cash"] == account["cash"], str(reloaded_account))
    assert_true(
        "restart_persist_orders",
        len(reloaded.list_orders("alpha")) == len(engine.list_orders("alpha")),
        f"before={len(engine.list_orders('alpha'))} after={len(reloaded.list_orders('alpha'))}",
    )

    print("SUMMARY PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL {exc}")
        sys.exit(1)
