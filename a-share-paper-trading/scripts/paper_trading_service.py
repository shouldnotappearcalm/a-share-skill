#!/usr/bin/env python3
"""Run the paper trading backend service."""

from __future__ import annotations

import argparse
from pathlib import Path

from paper_trading.engine import PaperTradingEngine
from paper_trading.service import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Paper trading backend service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db-path", default=str(Path(__file__).resolve().parent.parent / "cache" / "paper_trading.db"))
    parser.add_argument("--match-interval", type=int, default=5)
    parser.add_argument("--valuation-interval", type=int, default=10)
    parser.add_argument("--idle-valuation-interval", type=int, default=300)
    args = parser.parse_args()
    engine = PaperTradingEngine(db_path=args.db_path)
    print(f"paper trading service listening on http://{args.host}:{args.port} db={args.db_path}")
    run_server(args.host, args.port, engine, match_interval=args.match_interval, valuation_interval=args.valuation_interval, idle_valuation_interval=args.idle_valuation_interval)


if __name__ == "__main__":
    main()
