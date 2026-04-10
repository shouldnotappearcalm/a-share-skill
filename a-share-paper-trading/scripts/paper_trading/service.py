#!/usr/bin/env python3
"""HTTP service for the paper trading engine."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .engine import OrderRequest, PaperTradingEngine, is_trading_time


class MatchingLoop(threading.Thread):
    def __init__(self, engine: PaperTradingEngine, interval_seconds: int) -> None:
        super().__init__(daemon=True)
        self.engine = engine
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.engine.process_orders()
            except Exception:
                pass
            self._stop.wait(self.interval_seconds)

    def stop(self) -> None:
        self._stop.set()


class ValuationLoop(threading.Thread):
    def __init__(self, engine: PaperTradingEngine, trading_interval_seconds: int, idle_interval_seconds: int) -> None:
        super().__init__(daemon=True)
        self.engine = engine
        self.trading_interval_seconds = trading_interval_seconds
        self.idle_interval_seconds = idle_interval_seconds
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self.engine.snapshot_accounts()
            except Exception:
                pass
            interval = self.trading_interval_seconds if is_trading_time() else self.idle_interval_seconds
            self._stop.wait(interval)

    def stop(self) -> None:
        self._stop.set()


class TradingRequestHandler(BaseHTTPRequestHandler):
    engine: PaperTradingEngine = None

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            if path == "/health":
                return self._json({"status": "ok"})
            if path == "/accounts":
                return self._json({"status": "success", "data": self.engine.list_accounts()})
            if path == "/accounts/default":
                default_account_id = self.engine.get_default_account_id()
                if not default_account_id:
                    return self._json({"status": "error", "message": "default account not set"}, code=404)
                return self._json({"status": "success", "data": {"account_id": default_account_id}})
            if path.startswith("/accounts/") and path.endswith("/positions"):
                return self._json({"status": "success", "data": self.engine.get_positions(path.split("/")[2])})
            if path.startswith("/accounts/") and path.endswith("/orders"):
                account_id = path.split("/")[2]
                return self._json({"status": "success", "data": self.engine.list_orders(account_id, status=qs.get("status", [None])[0])})
            if path.startswith("/accounts/") and path.endswith("/trades"):
                return self._json({"status": "success", "data": self.engine.list_trades(path.split("/")[2])})
            if path.startswith("/accounts/") and len(path.split("/")) == 3:
                return self._json({"status": "success", "data": self.engine.get_account(path.split("/")[2])})
            return self._json({"status": "error", "message": f"unknown route {path}"}, code=404)
        except Exception as exc:
            return self._json({"status": "error", "message": str(exc)}, code=400)

    def do_POST(self) -> None:
        try:
            payload = self._payload()
            path = urlparse(self.path).path
            if path == "/accounts":
                return self._json({"status": "success", "data": self.engine.create_account(payload["account_id"], float(payload.get("initial_cash", 100000.0)))}, code=201)
            if path.startswith("/accounts/") and path.endswith("/reset"):
                return self._json({"status": "success", "data": self.engine.reset_account(path.split("/")[2], payload.get("initial_cash"))})
            if path == "/accounts/default":
                return self._json({"status": "success", "data": self.engine.set_default_account(payload["account_id"])})
            if path.startswith("/accounts/") and path.endswith("/cash-adjust"):
                account_id = path.split("/")[2]
                return self._json(
                    {
                        "status": "success",
                        "data": self.engine.adjust_cash(account_id, float(payload["delta"]), payload.get("note", "")),
                    }
                )
            if path == "/orders":
                req = OrderRequest(
                    account_id=payload["account_id"],
                    symbol=payload["symbol"],
                    side=payload["side"],
                    qty=int(payload["qty"]),
                    order_type=payload.get("order_type", "limit"),
                    limit_price=float(payload["limit_price"]) if payload.get("limit_price") is not None else None,
                    note=payload.get("note", ""),
                )
                return self._json({"status": "success", "data": self.engine.place_order(req)}, code=201)
            if path.startswith("/orders/") and path.endswith("/cancel"):
                return self._json({"status": "success", "data": self.engine.cancel_order(path.split("/")[2])})
            if path == "/orders/process":
                return self._json({"status": "success", "data": self.engine.process_orders()})
            if path == "/snapshots/run":
                return self._json({"status": "success", "data": self.engine.snapshot_accounts()})
            if path == "/backtest":
                return self._json(
                    {
                        "status": "success",
                        "data": self.engine.run_backtest(
                            symbol=payload["symbol"],
                            strategy=payload.get("strategy", "sma_cross"),
                            start=payload["start"],
                            end=payload["end"],
                            initial_cash=float(payload.get("initial_cash", 100000.0)),
                            params=payload.get("params") or {},
                        ),
                    }
                )
            return self._json({"status": "error", "message": f"unknown route {path}"}, code=404)
        except Exception as exc:
            return self._json({"status": "error", "message": str(exc)}, code=400)

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _payload(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _json(self, data: Dict[str, Any], code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int, engine: PaperTradingEngine, match_interval: int = 5, valuation_interval: int = 10, idle_valuation_interval: int = 300) -> None:
    TradingRequestHandler.engine = engine
    server = ThreadingHTTPServer((host, port), TradingRequestHandler)
    matching_loop = MatchingLoop(engine, match_interval)
    valuation_loop = ValuationLoop(engine, valuation_interval, idle_valuation_interval)
    matching_loop.start()
    valuation_loop.start()
    try:
        server.serve_forever()
    finally:
        matching_loop.stop()
        valuation_loop.stop()
        server.server_close()
