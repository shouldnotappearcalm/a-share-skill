#!/usr/bin/env python3
"""Scan mainboard liquidity pool and emit buy/sell signals (no backtest, no order execution)."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pandas as pd

from paper_trading.market_data import MarketDataProvider
from strategy_lab.strategies import trend_pullback
from strategy_lab import strategy_params


def _parse_holdings(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 6:
            out.append(digits[-6:].zfill(6))
    return out


def _row_snapshot(enriched: pd.DataFrame, idx: int) -> dict | None:
    if idx < 0 or idx >= len(enriched):
        return None
    row = enriched.iloc[idx]
    rsi_period = int(strategy_params.TREND_PULLBACK_PARAMS.get("rsi_period", 14))
    rsi_key = f"rsi_{rsi_period}"
    ts = row["time"]
    date_s = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
    rsi_val = float(row[rsi_key]) if rsi_key in row.index and pd.notna(row[rsi_key]) else None
    return {
        "date": date_s,
        "close": round(float(row["close"]), 4),
        "score": round(float(row["score"]), 6),
        "rsi": None if rsi_val is None else round(rsi_val, 4),
        "entry": bool(row["entry"]),
        "exit": bool(row["exit"]),
    }


def _scan_one(
    provider: MarketDataProvider,
    code: str,
    history_count: int,
) -> tuple[str, pd.DataFrame | None, str | None]:
    try:
        df = provider.get_history(code, count=history_count)
        if df is None or len(df) < max(
            int(strategy_params.TREND_PULLBACK_PARAMS.get("slow", 20)) + 3,
            30,
        ):
            return code, None, "short_history"
        out = trend_pullback(df, strategy_params.TREND_PULLBACK_PARAMS)
        return code, out, None
    except Exception as exc:
        return code, None, str(exc)[:200]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mainboard pool + trend_pullback: buy/sell signals for decision support",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=strategy_params.UNIVERSE_TOP_N_DEFAULT,
        help="Mainboard universe size by turnover",
    )
    parser.add_argument(
        "--history-count",
        type=int,
        default=120,
        help="Daily bars to fetch per symbol",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Parallel workers for history fetch",
    )
    parser.add_argument(
        "--holdings",
        type=Path,
        default=None,
        help="Optional file: one stock code per line, check sell signals",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print one JSON object to stdout",
    )
    parser.add_argument(
        "--max-buys",
        type=int,
        default=strategy_params.MAX_BUY_CANDIDATES,
        help="Cap buy lists after score sort; 0 means no cap",
    )
    args = parser.parse_args()

    provider = MarketDataProvider()
    universe = provider.get_mainboard_universe(as_of=None, top_n=int(args.top_n))
    if not universe:
        print("ERROR: empty universe", file=sys.stderr)
        sys.exit(1)

    rows: list[tuple[str, pd.DataFrame | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
        futs = {pool.submit(_scan_one, provider, c, int(args.history_count)): c for c in universe}
        for fut in as_completed(futs):
            rows.append(fut.result())

    buy_prev: list[dict] = []
    buy_last: list[dict] = []
    errors: list[dict] = []

    for code, enriched, err in rows:
        if err:
            errors.append({"code": code, "error": err})
            continue
        assert enriched is not None
        last = _row_snapshot(enriched, len(enriched) - 1)
        prev = _row_snapshot(enriched, len(enriched) - 2) if len(enriched) >= 2 else None
        if prev and prev.get("entry"):
            item = {"code": code, "signal_bar": prev, "asof_bar": last}
            buy_prev.append(item)
        if last and last.get("entry"):
            buy_last.append({"code": code, "signal_bar": last})

    buy_prev.sort(key=lambda x: float(x["signal_bar"]["score"]), reverse=True)
    buy_last.sort(key=lambda x: float(x["signal_bar"]["score"]), reverse=True)

    cap = int(args.max_buys)
    if cap > 0:
        buy_prev_out = buy_prev[:cap]
        buy_last_out = buy_last[:cap]
    else:
        buy_prev_out = buy_prev
        buy_last_out = buy_last

    holdings = _parse_holdings(args.holdings) if args.holdings else []
    sell_signals: list[dict] = []
    for code in holdings:
        enriched = None
        for c, en, err in rows:
            if c == code and en is not None:
                enriched = en
                break
        if enriched is None or enriched.empty:
            try:
                df = provider.get_history(code, count=int(args.history_count))
                enriched = trend_pullback(df, strategy_params.TREND_PULLBACK_PARAMS)
            except Exception as exc:
                sell_signals.append({"code": code, "error": str(exc)[:200]})
                continue
        last = _row_snapshot(enriched, len(enriched) - 1)
        if last and last.get("exit"):
            nm = ""
            try:
                nm = provider.get_quote(code).name or ""
            except Exception:
                pass
            sell_signals.append({"code": code, "name": nm, "signal_bar": last})

    names: dict[str, str] = {}
    for bucket in (buy_prev_out, buy_last_out):
        for item in bucket:
            c = item["code"]
            if c not in names:
                try:
                    names[c] = provider.get_quote(c).name or ""
                except Exception:
                    names[c] = ""
            item["name"] = names[c]

    latest_bar_date = None
    for _, enriched, err in rows:
        if err or enriched is None or enriched.empty:
            continue
        t = enriched.iloc[-1]["time"]
        latest_bar_date = t.strftime("%Y-%m-%d") if hasattr(t, "strftime") else str(t)[:10]
        break

    payload = {
        "strategy": strategy_params.STRATEGY_NAME,
        "latest_bar_date": latest_bar_date,
        "universe_size": len(universe),
        "max_buy_candidates": cap if cap > 0 else None,
        "params": strategy_params.TREND_PULLBACK_PARAMS,
        "reference_intraday_stop_pct": strategy_params.REFERENCE_INTRADAY_STOP_PCT,
        "buy": {
            "from_previous_day_close": buy_prev_out,
            "from_last_close": buy_last_out,
            "from_previous_day_close_total": len(buy_prev),
            "from_last_close_total": len(buy_last),
        },
        "sell": sell_signals,
        "errors_sample": errors[:20],
        "errors_total": len(errors),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print("strategy", payload["strategy"])
    print("latest_bar_date", latest_bar_date)
    print("universe_size", len(universe))
    if cap > 0:
        print("max_buy_candidates", cap, "shown", len(buy_prev_out), "/", len(buy_prev), "and", len(buy_last_out), "/", len(buy_last))
    print()
    print("=== 买入参考：上一交易日收盘出现 entry（适合与 T-1 信号、当日执行对齐）===")
    for item in buy_prev_out:
        sb = item["signal_bar"]
        print(
            item["code"],
            item.get("name", ""),
            "score",
            sb["score"],
            "rsi",
            sb["rsi"],
            "date",
            sb["date"],
        )
    if not buy_prev_out:
        print("(无)")
    print()
    print("=== 买入参考：最新一根日线收盘也出现 entry（形态展示，注意与 T-1 语义不同）===")
    for item in buy_last_out:
        sb = item["signal_bar"]
        print(
            item["code"],
            item.get("name", ""),
            "score",
            sb["score"],
            "rsi",
            sb["rsi"],
            "date",
            sb["date"],
        )
    if not buy_last_out:
        print("(无)")
    print()
    print("=== 卖出参考：持仓且最新收盘满足 exit ===")
    if args.holdings:
        for item in sell_signals:
            if "error" in item:
                print(item["code"], "error", item["error"])
            else:
                sb = item["signal_bar"]
                print(
                    item["code"],
                    item.get("name", ""),
                    "exit_date",
                    sb["date"],
                    "close",
                    sb["close"],
                    "rsi",
                    sb["rsi"],
                )
        if not sell_signals:
            print("(无)")
    else:
        print("未传 --holdings，跳过持仓卖出扫描")


if __name__ == "__main__":
    main()
