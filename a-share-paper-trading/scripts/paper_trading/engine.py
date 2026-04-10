#!/usr/bin/env python3
"""Core paper trading engine with SQLite persistence."""

from __future__ import annotations

import sqlite3
import threading
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, time as time_type
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from .market_data import MarketDataProvider


def now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def trade_date() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def market_phase(dt: Optional[datetime] = None) -> str:
    now = dt or datetime.now()
    if now.weekday() >= 5:
        return "closed"
    current = now.time()
    if time_type(9, 15) <= current < time_type(9, 25):
        return "opening_call_auction"
    if time_type(9, 25) <= current < time_type(9, 30):
        return "pre_open_break"
    if time_type(9, 30) <= current <= time_type(11, 30):
        return "morning_continuous"
    if time_type(11, 30) < current < time_type(13, 0):
        return "lunch_break"
    if time_type(13, 0) <= current < time_type(14, 57):
        return "afternoon_continuous"
    if time_type(14, 57) <= current <= time_type(15, 0):
        return "closing_call_auction"
    return "post_close"


def is_trading_time(dt: Optional[datetime] = None) -> bool:
    return market_phase(dt) in {"morning_continuous", "afternoon_continuous"}


def is_after_close(dt: Optional[datetime] = None) -> bool:
    now = dt or datetime.now()
    if now.weekday() >= 5:
        return True
    return now.time() > time_type(15, 0)


def _is_shanghai_symbol(symbol: Optional[str]) -> bool:
    if not symbol:
        return False
    value = str(symbol).strip().lower()
    return value.startswith("sh") or value.startswith("6")


def calc_transfer_fee(amount: float, symbol: Optional[str] = None) -> float:
    if not _is_shanghai_symbol(symbol):
        return 0.0
    return round(amount * 0.00001, 2)


def calc_commission(amount: float, symbol: Optional[str] = None) -> float:
    broker = max(5.0, round(amount * 0.0003, 2))
    return round(broker + calc_transfer_fee(amount, symbol), 2)


def calc_tax(side: str, amount: float) -> float:
    return 0.0 if side.lower() != "sell" else round(amount * 0.001, 2)


def validate_price_tick(price: float) -> float:
    try:
        price_decimal = Decimal(str(price))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid price {price}") from exc
    normalized = price_decimal.quantize(Decimal("0.01"))
    if price_decimal != normalized:
        raise ValueError(f"order price must align with 0.01 tick size, got {price}")
    return float(normalized)


@dataclass
class OrderRequest:
    account_id: str
    symbol: str
    side: str
    qty: int
    order_type: str = "limit"
    limit_price: Optional[float] = None
    note: str = ""


class PaperTradingEngine:
    def __init__(self, db_path: str, market_data: Optional[MarketDataProvider] = None) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.market_data = market_data or MarketDataProvider()
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_id TEXT PRIMARY KEY,
                    initial_cash REAL NOT NULL,
                    cash REAL NOT NULL,
                    frozen_cash REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    limit_price REAL,
                    qty INTEGER NOT NULL,
                    reserved_cash REAL NOT NULL DEFAULT 0,
                    filled_qty INTEGER NOT NULL DEFAULT 0,
                    avg_fill_price REAL,
                    status TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    last_checked_at TEXT,
                    validity TEXT NOT NULL DEFAULT 'day',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    price REAL NOT NULL,
                    qty INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    commission REAL NOT NULL,
                    tax REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS position_lots (
                    lot_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    acquired_date TEXT NOT NULL,
                    qty INTEGER NOT NULL,
                    remaining_qty INTEGER NOT NULL,
                    cost_price REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL,
                    snapshot_time TEXT NOT NULL,
                    cash REAL NOT NULL,
                    frozen_cash REAL NOT NULL,
                    market_value REAL NOT NULL,
                    net_asset REAL NOT NULL,
                    position_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS system_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )

    def create_account(self, account_id: str, initial_cash: float) -> Dict:
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT account_id FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            if existing:
                raise ValueError(f"account {account_id} already exists")
            account_count = conn.execute("SELECT COUNT(*) AS cnt FROM accounts").fetchone()["cnt"]
            ts = now_ts()
            conn.execute(
                "INSERT INTO accounts(account_id, initial_cash, cash, frozen_cash, created_at, updated_at) VALUES(?, ?, ?, 0, ?, ?)",
                (account_id, float(initial_cash), float(initial_cash), ts, ts),
            )
            if int(account_count or 0) == 0:
                conn.execute(
                    "INSERT OR REPLACE INTO system_settings(key, value) VALUES('default_account_id', ?)",
                    (account_id,),
                )
        return self.get_account(account_id)

    def list_accounts(self) -> List[Dict]:
        default_account_id = self.get_default_account_id()
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT account_id FROM accounts ORDER BY account_id").fetchall()
        out = []
        for row in rows:
            item = self.get_account(row["account_id"])
            item["is_default"] = row["account_id"] == default_account_id
            out.append(item)
        return out

    def get_default_account_id(self) -> Optional[str]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key = 'default_account_id'").fetchone()
            if not row:
                return None
            account = conn.execute("SELECT account_id FROM accounts WHERE account_id = ?", (row["value"],)).fetchone()
            return account["account_id"] if account else None

    def set_default_account(self, account_id: str) -> Dict:
        with self._lock, self._connect() as conn:
            account = conn.execute("SELECT account_id FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            if not account:
                raise ValueError(f"account {account_id} not found")
            conn.execute(
                "INSERT OR REPLACE INTO system_settings(key, value) VALUES('default_account_id', ?)",
                (account_id,),
            )
        return {"default_account_id": account_id}

    def adjust_cash(self, account_id: str, delta: float, note: str = "") -> Dict:
        delta = round(float(delta), 2)
        if abs(delta) < 1e-9:
            raise ValueError("delta must not be zero")
        with self._lock, self._connect() as conn:
            account = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            if not account:
                raise ValueError(f"account {account_id} not found")
            available_cash = float(account["cash"]) - float(account["frozen_cash"])
            if delta < 0 and available_cash + 1e-6 < abs(delta):
                raise ValueError(f"insufficient available cash, available={round(available_cash, 2)}")
            ts = now_ts()
            conn.execute(
                "UPDATE accounts SET initial_cash = initial_cash + ?, cash = cash + ?, updated_at = ? WHERE account_id = ?",
                (delta, delta, ts, account_id),
            )
        account_data = self.get_account(account_id)
        account_data["cash_adjustment"] = {"delta": delta, "note": note}
        return account_data

    def reset_account(self, account_id: str, initial_cash: Optional[float] = None) -> Dict:
        with self._lock, self._connect() as conn:
            account = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            if not account:
                raise ValueError(f"account {account_id} not found")
            base_cash = float(initial_cash if initial_cash is not None else account["initial_cash"])
            ts = now_ts()
            conn.execute(
                "UPDATE accounts SET initial_cash = ?, cash = ?, frozen_cash = 0, updated_at = ? WHERE account_id = ?",
                (base_cash, base_cash, ts, account_id),
            )
            conn.execute("DELETE FROM orders WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM trades WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM position_lots WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM account_snapshots WHERE account_id = ?", (account_id,))
        return self.get_account(account_id)

    def place_order(self, req: OrderRequest) -> Dict:
        req.symbol = self.market_data.normalize_symbol(req.symbol)
        req.side = req.side.lower()
        req.order_type = req.order_type.lower()
        if req.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if req.order_type not in {"limit", "market"}:
            raise ValueError("order_type must be limit or market")
        if req.qty <= 0:
            raise ValueError("qty must be positive")
        if req.side == "buy" and req.qty % 100 != 0:
            raise ValueError("A-share buy order qty must be multiple of 100")
        if req.order_type == "limit" and (req.limit_price is None or req.limit_price <= 0):
            raise ValueError("limit_price required for limit orders")
        if req.order_type == "market" and not is_trading_time():
            raise ValueError("market orders are only accepted during trading hours")
        if req.order_type == "limit" and req.limit_price is not None:
            req.limit_price = validate_price_tick(req.limit_price)

        quote = self.market_data.get_quote(req.symbol)
        if req.order_type == "market" and not self._is_quote_tradable(quote):
            raise ValueError(f"symbol {req.symbol} quote is stale or unavailable for market order")
        self._validate_price_limits(req, quote)
        with self._lock, self._connect() as conn:
            account = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (req.account_id,)).fetchone()
            if not account:
                raise ValueError(f"account {req.account_id} not found")

            reserved_cash = 0.0
            if req.side == "buy":
                if req.order_type == "limit":
                    reserved_cash = req.qty * float(req.limit_price) + calc_commission(req.qty * float(req.limit_price), req.symbol)
                    available_cash = float(account["cash"]) - float(account["frozen_cash"])
                    if available_cash + 1e-6 < reserved_cash:
                        raise ValueError("insufficient available cash")
                else:
                    estimated_amount = req.qty * quote.price
                    total_need = estimated_amount + calc_commission(estimated_amount, req.symbol)
                    available_cash = float(account["cash"]) - float(account["frozen_cash"])
                    if available_cash + 1e-6 < total_need:
                        raise ValueError("insufficient available cash")
            else:
                available_sellable = self._get_sellable_qty(conn, req.account_id, req.symbol) - self._get_pending_sell_qty(conn, req.account_id, req.symbol)
                if available_sellable < req.qty:
                    raise ValueError(f"insufficient sellable qty, available={available_sellable}")
                total_position = self._get_total_qty(conn, req.account_id, req.symbol)
                if req.qty % 100 != 0 and req.qty != total_position:
                    raise ValueError("A-share sell qty must be multiple of 100 unless selling all remaining shares")

            order_id = uuid.uuid4().hex[:16]
            ts = now_ts()
            conn.execute(
                """
                INSERT INTO orders(order_id, account_id, symbol, side, order_type, limit_price, qty, reserved_cash, filled_qty, avg_fill_price, status, note, last_checked_at, validity, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, 'open', ?, ?, 'day', ?, ?)
                """,
                (order_id, req.account_id, req.symbol, req.side, req.order_type, req.limit_price, req.qty, reserved_cash, req.note, ts, ts, ts),
            )
            if reserved_cash > 0:
                conn.execute("UPDATE accounts SET frozen_cash = frozen_cash + ?, updated_at = ? WHERE account_id = ?", (reserved_cash, ts, req.account_id))

        if req.order_type == "market":
            self.process_orders()
        return self.get_order(order_id)

    def cancel_order(self, order_id: str) -> Dict:
        with self._lock, self._connect() as conn:
            order = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if not order:
                raise ValueError(f"order {order_id} not found")
            if order["status"] != "open":
                raise ValueError(f"order {order_id} is not open")
            ts = now_ts()
            if float(order["reserved_cash"]) > 0:
                conn.execute("UPDATE accounts SET frozen_cash = MAX(0, frozen_cash - ?), updated_at = ? WHERE account_id = ?", (float(order["reserved_cash"]), ts, order["account_id"]))
            conn.execute("UPDATE orders SET status = 'cancelled', updated_at = ? WHERE order_id = ?", (ts, order_id))
        return self.get_order(order_id)

    def process_orders(self) -> Dict:
        if not is_trading_time():
            expired = self.expire_day_orders()
            return {"processed": 0, "filled": 0, "expired": expired}
        with self._lock, self._connect() as conn:
            open_orders = conn.execute("SELECT * FROM orders WHERE status = 'open' ORDER BY created_at ASC").fetchall()
            if not open_orders:
                return {"processed": 0, "filled": 0}
            filled = 0
            for order in open_orders:
                quote = self.market_data.get_quote(order["symbol"])
                if not self._is_quote_tradable(quote):
                    ts = now_ts()
                    conn.execute("UPDATE orders SET last_checked_at = ?, updated_at = ? WHERE order_id = ?", (ts, ts, order["order_id"]))
                    continue
                market_date = quote.timestamp.split(" ")[0] if quote.timestamp else trade_date()
                fill_price = self._get_fill_price(order, quote)
                if fill_price is not None:
                    self._fill_order(conn, order, fill_price, market_date)
                    filled += 1
                else:
                    ts = now_ts()
                    conn.execute("UPDATE orders SET last_checked_at = ?, updated_at = ? WHERE order_id = ?", (ts, ts, order["order_id"]))
            return {"processed": len(open_orders), "filled": filled, "expired": 0}

    def expire_day_orders(self) -> int:
        if not is_after_close():
            return 0
        with self._lock, self._connect() as conn:
            open_orders = conn.execute("SELECT * FROM orders WHERE status = 'open' AND validity = 'day' ORDER BY created_at ASC").fetchall()
            expired = 0
            for order in open_orders:
                ts = now_ts()
                if float(order["reserved_cash"]) > 0:
                    conn.execute("UPDATE accounts SET frozen_cash = MAX(0, frozen_cash - ?), updated_at = ? WHERE account_id = ?", (float(order["reserved_cash"]), ts, order["account_id"]))
                conn.execute("UPDATE orders SET status = 'expired', note = ?, updated_at = ? WHERE order_id = ?", ("expired at market close", ts, order["order_id"]))
                expired += 1
            return expired

    def snapshot_accounts(self) -> Dict:
        accounts = self.list_accounts()
        with self._lock, self._connect() as conn:
            ts = now_ts()
            for account in accounts:
                conn.execute(
                    """
                    INSERT INTO account_snapshots(snapshot_id, account_id, snapshot_time, cash, frozen_cash, market_value, net_asset, position_count)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex[:16],
                        account["account_id"],
                        ts,
                        account["cash"],
                        account["frozen_cash"],
                        account["market_value"],
                        account["net_asset"],
                        len(account["positions"]),
                    ),
                )
        return {"snapshots": len(accounts), "timestamp": ts}

    def get_order(self, order_id: str) -> Dict:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
            if not row:
                raise ValueError(f"order {order_id} not found")
            return dict(row)

    def list_orders(self, account_id: str, status: Optional[str] = None) -> List[Dict]:
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM orders WHERE account_id = ? AND status = ? ORDER BY created_at DESC", (account_id, status)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM orders WHERE account_id = ? ORDER BY created_at DESC", (account_id,)).fetchall()
        return [dict(row) for row in rows]

    def list_trades(self, account_id: str) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM trades WHERE account_id = ? ORDER BY created_at DESC", (account_id,)).fetchall()
        return [dict(row) for row in rows]

    def get_positions(self, account_id: str) -> List[Dict]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT symbol, SUM(remaining_qty) AS qty, SUM(remaining_qty * cost_price) AS cost_amount
                FROM position_lots
                WHERE account_id = ? AND remaining_qty > 0
                GROUP BY symbol
                ORDER BY symbol
                """,
                (account_id,),
            ).fetchall()
            symbols = [row["symbol"] for row in rows]
            quotes = self.market_data.get_quotes(symbols) if symbols else {}
            out = []
            for row in rows:
                qty = int(row["qty"] or 0)
                cost_amount = float(row["cost_amount"] or 0.0)
                avg_cost = cost_amount / qty if qty else 0.0
                quote = quotes.get(row["symbol"])
                last_price = quote.price if quote else avg_cost
                market_value = last_price * qty
                out.append(
                    {
                        "symbol": row["symbol"],
                        "qty": qty,
                        "sellable_qty": self._get_sellable_qty(conn, account_id, row["symbol"]),
                        "avg_cost": round(avg_cost, 4),
                        "last_price": round(last_price, 4),
                        "market_value": round(market_value, 2),
                        "unrealized_pnl": round(market_value - cost_amount, 2),
                    }
                )
        return out

    def get_account(self, account_id: str) -> Dict:
        with self._lock, self._connect() as conn:
            account = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (account_id,)).fetchone()
            if not account:
                raise ValueError(f"account {account_id} not found")
            positions = self.get_positions(account_id)
            market_value = round(sum(item["market_value"] for item in positions), 2)
            net_asset = round(float(account["cash"]) + market_value, 2)
            return {
                "account_id": account_id,
                "initial_cash": round(float(account["initial_cash"]), 2),
                "cash": round(float(account["cash"]), 2),
                "frozen_cash": round(float(account["frozen_cash"]), 2),
                "available_cash": round(float(account["cash"]) - float(account["frozen_cash"]), 2),
                "market_value": market_value,
                "net_asset": net_asset,
                "positions": positions,
                "order_count": len(self.list_orders(account_id)),
                "trade_count": len(self.list_trades(account_id)),
                "cash_flow_pnl": round(net_asset - float(account["initial_cash"]), 2),
                "updated_at": account["updated_at"],
            }

    def run_backtest(self, symbol: str, strategy: str, start: str, end: str, initial_cash: float, params: Optional[Dict] = None) -> Dict:
        params = params or {}
        bars = self.market_data.get_history(symbol, start=start, end=end, count=params.get("count", 500))
        if len(bars) < 30:
            raise ValueError("not enough bars for backtest")
        cash = float(initial_cash)
        qty = 0
        avg_cost = 0.0
        trades: List[Dict] = []
        equity_curve: List[Dict] = []
        bars = bars.copy()
        bars["ma_fast"] = bars["close"].rolling(int(params.get("fast", 5))).mean()
        bars["ma_slow"] = bars["close"].rolling(int(params.get("slow", 20))).mean()
        delta = bars["close"].diff()
        gain = delta.where(delta > 0, 0.0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
        rs = gain / loss.replace(0, pd.NA)
        bars["rsi"] = 100 - (100 / (1 + rs))
        for i, row in bars.iterrows():
            price = float(row["close"])
            date_str = row["time"].strftime("%Y-%m-%d")
            signal = "hold"
            if strategy == "buy_and_hold":
                if i == 0 and qty == 0:
                    signal = "buy"
            elif strategy == "sma_cross":
                if i > 0 and pd.notna(row["ma_fast"]) and pd.notna(row["ma_slow"]):
                    prev = bars.iloc[i - 1]
                    if prev["ma_fast"] <= prev["ma_slow"] and row["ma_fast"] > row["ma_slow"]:
                        signal = "buy"
                    elif prev["ma_fast"] >= prev["ma_slow"] and row["ma_fast"] < row["ma_slow"]:
                        signal = "sell"
            elif strategy == "rsi_revert":
                if pd.notna(row["rsi"]):
                    if row["rsi"] < float(params.get("buy_rsi", 30)) and qty == 0:
                        signal = "buy"
                    elif row["rsi"] > float(params.get("sell_rsi", 70)) and qty > 0:
                        signal = "sell"
            else:
                raise ValueError("unsupported strategy")
            if signal == "buy" and qty == 0:
                lot_qty = int((cash / price) // 100) * 100
                if lot_qty >= 100:
                    amount = lot_qty * price
                    commission = calc_commission(amount, symbol)
                    cash -= amount + commission
                    qty = lot_qty
                    avg_cost = price
                    trades.append({"date": date_str, "action": "buy", "price": round(price, 3), "qty": lot_qty, "amount": round(amount, 2), "profit": 0.0})
            elif signal == "sell" and qty > 0:
                amount = qty * price
                commission = calc_commission(amount, symbol)
                tax = calc_tax("sell", amount)
                profit = amount - commission - tax - qty * avg_cost
                cash += amount - commission - tax
                trades.append({"date": date_str, "action": "sell", "price": round(price, 3), "qty": qty, "amount": round(amount, 2), "profit": round(profit, 2)})
                qty = 0
                avg_cost = 0.0
            equity_curve.append({"date": date_str, "equity": round(cash + qty * price, 2)})
        final_price = float(bars.iloc[-1]["close"])
        final_equity = cash + qty * final_price
        peak = 0.0
        max_drawdown = 0.0
        for item in equity_curve:
            peak = max(peak, item["equity"])
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - item["equity"]) / peak)
        sell_profits = [trade["profit"] for trade in trades if trade["action"] == "sell"]
        return {
            "symbol": self.market_data.normalize_symbol(symbol),
            "strategy": strategy,
            "initial_capital": round(initial_cash, 2),
            "final_capital": round(final_equity, 2),
            "total_return_pct": round((final_equity - initial_cash) / initial_cash * 100.0, 2),
            "max_drawdown_pct": round(max_drawdown * 100.0, 2),
            "win_count": len([p for p in sell_profits if p > 0]),
            "loss_count": len([p for p in sell_profits if p <= 0]),
            "trades": trades,
            "equity_curve": equity_curve[-60:],
        }

    def _validate_price_limits(self, req: OrderRequest, quote) -> None:
        if req.order_type != "limit" or req.limit_price is None:
            return
        if quote.limit_up is None or quote.limit_down is None:
            return
        price = validate_price_tick(req.limit_price)
        limit_up = round(float(quote.limit_up), 2)
        limit_down = round(float(quote.limit_down), 2)
        if price > limit_up:
            raise ValueError(f"order price {price} above daily limit up {limit_up}")
        if price < limit_down:
            raise ValueError(f"order price {price} below daily limit down {limit_down}")

    def _is_quote_tradable(self, quote) -> bool:
        try:
            if float(quote.price) <= 0:
                return False
            if max(float(quote.open), float(quote.high), float(quote.low), float(quote.price)) <= 0:
                return False
        except Exception:
            return False
        if not getattr(quote, "timestamp", None):
            return False
        try:
            quote_date = str(quote.timestamp).split(" ")[0]
        except Exception:
            return False
        return quote_date == trade_date()

    def _should_fill(self, order: sqlite3.Row, last_price: float) -> bool:
        if order["order_type"] == "market":
            return True
        limit_price = float(order["limit_price"])
        return last_price <= limit_price + 1e-9 if order["side"] == "buy" else last_price >= limit_price - 1e-9

    def _is_locked_limit(self, side: str, quote) -> bool:
        if quote.limit_up is None or quote.limit_down is None:
            return False
        price = round(float(quote.price), 2)
        open_price = round(float(quote.open), 2)
        high_price = round(float(quote.high), 2)
        low_price = round(float(quote.low), 2)
        limit_up = round(float(quote.limit_up), 2)
        limit_down = round(float(quote.limit_down), 2)
        if side == "buy":
            return price >= limit_up and open_price >= limit_up and low_price >= limit_up
        return price <= limit_down and open_price <= limit_down and high_price <= limit_down

    def _can_fill_buy_on_bar(self, limit_price: float, quote, bar_low: float) -> bool:
        if bar_low > limit_price + 1e-9:
            return False
        if quote.limit_up is not None and round(float(quote.price), 2) >= round(float(quote.limit_up), 2):
            return bar_low < round(float(quote.limit_up), 2) - 1e-9
        return True

    def _can_fill_sell_on_bar(self, limit_price: float, quote, bar_high: float) -> bool:
        if bar_high < limit_price - 1e-9:
            return False
        if quote.limit_down is not None and round(float(quote.price), 2) <= round(float(quote.limit_down), 2):
            return bar_high > round(float(quote.limit_down), 2) + 1e-9
        return True

    def _can_fill_with_quote_only(self, side: str, quote) -> bool:
        if side == "buy" and quote.limit_up is not None and round(float(quote.price), 2) >= round(float(quote.limit_up), 2):
            return False
        if side == "sell" and quote.limit_down is not None and round(float(quote.price), 2) <= round(float(quote.limit_down), 2):
            return False
        return True

    def _get_fill_price(self, order: sqlite3.Row, quote) -> Optional[float]:
        if not self._is_quote_tradable(quote):
            return None
        if order["order_type"] == "market":
            return None if self._is_locked_limit(order["side"], quote) else quote.price
        limit_price = float(order["limit_price"])
        if self._is_locked_limit(order["side"], quote):
            return None
        last_checked = order["last_checked_at"] or order["created_at"]
        try:
            last_checked_dt = pd.to_datetime(last_checked)
        except Exception:
            last_checked_dt = pd.Timestamp.now() - pd.Timedelta(minutes=5)
        bars = self.market_data.get_intraday_bars(order["symbol"], freq="1m", count=240)
        if not bars.empty:
            recent = bars[bars["time"] >= last_checked_dt.floor("min")]
            if not recent.empty:
                for _, bar in recent.iterrows():
                    bar_low = float(bar["low"])
                    bar_high = float(bar["high"])
                    bar_open = float(bar["open"])
                    if order["side"] == "buy" and self._can_fill_buy_on_bar(limit_price, quote, bar_low):
                        return min(limit_price, bar_open) if bar_open <= limit_price else limit_price
                    if order["side"] == "sell" and self._can_fill_sell_on_bar(limit_price, quote, bar_high):
                        return max(limit_price, bar_open) if bar_open >= limit_price else limit_price
        if self._should_fill(order, quote.price) and self._can_fill_with_quote_only(order["side"], quote):
            return min(limit_price, float(quote.price)) if order["side"] == "buy" else max(limit_price, float(quote.price))
        return None

    def _fill_order(self, conn: sqlite3.Connection, order: sqlite3.Row, fill_price: float, market_date: str) -> None:
        qty = int(order["qty"])
        amount = round(fill_price * qty, 2)
        commission = calc_commission(amount, order["symbol"])
        tax = calc_tax(order["side"], amount)
        ts = now_ts()
        if order["side"] == "buy":
            account = conn.execute("SELECT * FROM accounts WHERE account_id = ?", (order["account_id"],)).fetchone()
            if float(account["cash"]) + 1e-6 < amount + commission:
                conn.execute("UPDATE orders SET status = 'rejected', note = ?, updated_at = ? WHERE order_id = ?", ("insufficient cash at fill time", ts, order["order_id"]))
                if float(order["reserved_cash"]) > 0:
                    conn.execute("UPDATE accounts SET frozen_cash = MAX(0, frozen_cash - ?), updated_at = ? WHERE account_id = ?", (float(order["reserved_cash"]), ts, order["account_id"]))
                return
            conn.execute("UPDATE accounts SET cash = cash - ?, frozen_cash = MAX(0, frozen_cash - ?), updated_at = ? WHERE account_id = ?", (amount + commission, float(order["reserved_cash"]), ts, order["account_id"]))
            conn.execute(
                "INSERT INTO position_lots(lot_id, account_id, symbol, acquired_date, qty, remaining_qty, cost_price, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex[:16], order["account_id"], order["symbol"], market_date, qty, qty, fill_price, ts),
            )
        else:
            sellable_lots = conn.execute(
                "SELECT * FROM position_lots WHERE account_id = ? AND symbol = ? AND remaining_qty > 0 AND acquired_date < ? ORDER BY acquired_date ASC, created_at ASC",
                (order["account_id"], order["symbol"], trade_date()),
            ).fetchall()
            remaining = qty
            for lot in sellable_lots:
                if remaining <= 0:
                    break
                take_qty = min(remaining, int(lot["remaining_qty"]))
                conn.execute("UPDATE position_lots SET remaining_qty = remaining_qty - ? WHERE lot_id = ?", (take_qty, lot["lot_id"]))
                remaining -= take_qty
            if remaining > 0:
                conn.execute("UPDATE orders SET status = 'rejected', note = ?, updated_at = ? WHERE order_id = ?", ("insufficient sellable qty at fill time", ts, order["order_id"]))
                return
            conn.execute("UPDATE accounts SET cash = cash + ?, updated_at = ? WHERE account_id = ?", (amount - commission - tax, ts, order["account_id"]))
        conn.execute(
            "INSERT INTO trades(trade_id, order_id, account_id, symbol, side, price, qty, amount, commission, tax, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex[:16], order["order_id"], order["account_id"], order["symbol"], order["side"], fill_price, qty, amount, commission, tax, ts),
        )
        conn.execute("UPDATE orders SET filled_qty = ?, avg_fill_price = ?, status = 'filled', updated_at = ? WHERE order_id = ?", (qty, fill_price, ts, order["order_id"]))

    def _get_total_qty(self, conn: sqlite3.Connection, account_id: str, symbol: str) -> int:
        row = conn.execute("SELECT COALESCE(SUM(remaining_qty), 0) AS qty FROM position_lots WHERE account_id = ? AND symbol = ? AND remaining_qty > 0", (account_id, symbol)).fetchone()
        return int(row["qty"] or 0)

    def _get_sellable_qty(self, conn: sqlite3.Connection, account_id: str, symbol: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(SUM(remaining_qty), 0) AS qty FROM position_lots WHERE account_id = ? AND symbol = ? AND remaining_qty > 0 AND acquired_date < ?",
            (account_id, symbol, trade_date()),
        ).fetchone()
        return int(row["qty"] or 0)

    def _get_pending_sell_qty(self, conn: sqlite3.Connection, account_id: str, symbol: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(SUM(qty - filled_qty), 0) AS qty FROM orders WHERE account_id = ? AND symbol = ? AND side = 'sell' AND status = 'open'",
            (account_id, symbol),
        ).fetchone()
        return int(row["qty"] or 0)
