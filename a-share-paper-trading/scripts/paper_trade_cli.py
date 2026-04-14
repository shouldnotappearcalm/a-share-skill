#!/usr/bin/env python3
"""CLI entrypoint for the paper trading service."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from paper_trading_runtime import DEFAULT_HOST, DEFAULT_PORT


def request_json(base_url: str, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{base_url}{path}", data=data, headers={"Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8") if exc.fp else ""
        try:
            return json.loads(body)
        except Exception as err:
            raise RuntimeError(f"HTTP {exc.code}: {body}") from err
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to reach service at {base_url}: {exc}") from exc


def print_result(result: Dict[str, Any], output_json: bool) -> None:
    if output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("status") != "success":
        print(f"ERROR: {result.get('message')}")
        sys.exit(1)
    data = result.get("data")
    print(json.dumps(data, ensure_ascii=False, indent=2) if isinstance(data, (dict, list)) else data)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Paper trading CLI for a-share paper trading skill")
    parser.add_argument("--base-url", default=f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-account")
    create.add_argument("account_id")
    create.add_argument("--cash", type=float, default=100000.0)
    reset = sub.add_parser("reset-account")
    reset.add_argument("account_id")
    reset.add_argument("--cash", type=float)
    sub.add_parser("list-accounts")
    sub.add_parser("show-default-account")
    set_default = sub.add_parser("set-default-account")
    set_default.add_argument("account_id")
    show = sub.add_parser("show-account")
    show.add_argument("account_id")
    positions = sub.add_parser("positions")
    positions.add_argument("account_id")
    orders = sub.add_parser("orders")
    orders.add_argument("account_id")
    orders.add_argument("--status")
    trades = sub.add_parser("trades")
    trades.add_argument("account_id")
    buy = sub.add_parser("buy")
    buy.add_argument("account_id")
    buy.add_argument("symbol")
    buy.add_argument("qty", type=int)
    buy.add_argument("--price", type=float)
    buy.add_argument("--market", action="store_true")
    buy.add_argument("--note", default="")
    sell = sub.add_parser("sell")
    sell.add_argument("account_id")
    sell.add_argument("symbol")
    sell.add_argument("qty", type=int)
    sell.add_argument("--price", type=float)
    sell.add_argument("--market", action="store_true")
    sell.add_argument("--note", default="")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("order_id")
    add_cash = sub.add_parser("add-cash")
    add_cash.add_argument("account_id")
    add_cash.add_argument("amount", type=float)
    add_cash.add_argument("--note", default="")
    deduct_cash = sub.add_parser("deduct-cash")
    deduct_cash.add_argument("account_id")
    deduct_cash.add_argument("amount", type=float)
    deduct_cash.add_argument("--note", default="")
    sub.add_parser("process-orders")
    sub.add_parser("run-snapshots")
    backtest = sub.add_parser("backtest")
    backtest.add_argument("symbol")
    backtest.add_argument("--strategy", default="sma_cross", choices=["buy_and_hold", "sma_cross", "rsi_revert"])
    backtest.add_argument("--start", required=True)
    backtest.add_argument("--end", required=True)
    backtest.add_argument("--cash", type=float, default=100000.0)
    backtest.add_argument("--fast", type=int, default=5)
    backtest.add_argument("--slow", type=int, default=20)
    backtest.add_argument("--buy-rsi", type=float, default=30.0)
    backtest.add_argument("--sell-rsi", type=float, default=70.0)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    cmd = args.command
    if cmd == "create-account":
        result = request_json(base_url, "POST", "/accounts", {"account_id": args.account_id, "initial_cash": args.cash})
    elif cmd == "reset-account":
        result = request_json(base_url, "POST", f"/accounts/{args.account_id}/reset", {"initial_cash": args.cash})
    elif cmd == "list-accounts":
        result = request_json(base_url, "GET", "/accounts")
    elif cmd == "show-default-account":
        result = request_json(base_url, "GET", "/accounts/default")
    elif cmd == "set-default-account":
        result = request_json(base_url, "POST", "/accounts/default", {"account_id": args.account_id})
    elif cmd == "show-account":
        result = request_json(base_url, "GET", f"/accounts/{args.account_id}")
    elif cmd == "positions":
        result = request_json(base_url, "GET", f"/accounts/{args.account_id}/positions")
    elif cmd == "orders":
        suffix = f"?status={args.status}" if args.status else ""
        result = request_json(base_url, "GET", f"/accounts/{args.account_id}/orders{suffix}")
    elif cmd == "trades":
        result = request_json(base_url, "GET", f"/accounts/{args.account_id}/trades")
    elif cmd in {"buy", "sell"}:
        if not args.market and args.price is None:
            parser.error("limit order requires --price, or use --market")
        result = request_json(
            base_url,
            "POST",
            "/orders",
            {
                "account_id": args.account_id,
                "symbol": args.symbol,
                "side": cmd,
                "qty": args.qty,
                "order_type": "market" if args.market else "limit",
                "limit_price": args.price,
                "note": args.note,
            },
        )
    elif cmd == "cancel":
        result = request_json(base_url, "POST", f"/orders/{args.order_id}/cancel", {})
    elif cmd == "add-cash":
        if args.amount <= 0:
            parser.error("amount must be positive")
        result = request_json(
            base_url,
            "POST",
            f"/accounts/{args.account_id}/cash-adjust",
            {"delta": args.amount, "note": args.note},
        )
    elif cmd == "deduct-cash":
        if args.amount <= 0:
            parser.error("amount must be positive")
        result = request_json(
            base_url,
            "POST",
            f"/accounts/{args.account_id}/cash-adjust",
            {"delta": -args.amount, "note": args.note},
        )
    elif cmd == "process-orders":
        result = request_json(base_url, "POST", "/orders/process", {})
    elif cmd == "run-snapshots":
        result = request_json(base_url, "POST", "/snapshots/run", {})
    elif cmd == "backtest":
        result = request_json(
            base_url,
            "POST",
            "/backtest",
            {
                "symbol": args.symbol,
                "strategy": args.strategy,
                "start": args.start,
                "end": args.end,
                "initial_cash": args.cash,
                "params": {"fast": args.fast, "slow": args.slow, "buy_rsi": args.buy_rsi, "sell_rsi": args.sell_rsi},
            },
        )
    else:
        parser.error(f"unknown command {cmd}")
        return
    print_result(result, args.json)


if __name__ == "__main__":
    main()
