#!/usr/bin/env python3
"""Scan mainboard liquidity pool and emit buy/sell signals (no backtest, no order execution)."""

from __future__ import annotations

import argparse
import itertools
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


def _build_param_variants(base_params: dict, grid: dict) -> list[dict]:
    keys = [k for k, v in grid.items() if isinstance(v, list) and v]
    if not keys:
        return [dict(base_params)]
    values = [list(dict.fromkeys(grid[k])) for k in keys]
    variants: list[dict] = []
    for combo in itertools.product(*values):
        params = dict(base_params)
        for key, val in zip(keys, combo):
            params[key] = val
        variants.append(params)
    return variants


def _entry_consensus_ratio(df: pd.DataFrame, variants: list[dict], use_previous_day: bool) -> float:
    if df is None or df.empty or not variants:
        return 0.0
    idx = -2 if use_previous_day else -1
    if len(df) < 2 and use_previous_day:
        return 0.0
    votes = 0
    valid = 0
    for params in variants:
        try:
            enriched = trend_pullback(df, params)
            if enriched is None or enriched.empty:
                continue
            if abs(idx) > len(enriched):
                continue
            valid += 1
            if bool(enriched.iloc[idx].get("entry", False)):
                votes += 1
        except Exception:
            continue
    if valid == 0:
        return 0.0
    return votes / valid


def _edge_after_cost(signal_bar: dict, roundtrip_cost_bps: float) -> float:
    score = max(float(signal_bar.get("score", 0.0)), 0.0)
    cost = max(float(roundtrip_cost_bps), 0.0) / 10000.0
    return score - cost


def _passes_cost_filter(signal_bar: dict, roundtrip_cost_bps: float) -> bool:
    return _edge_after_cost(signal_bar, roundtrip_cost_bps) > 0


def _scan_one(
    provider: MarketDataProvider,
    code: str,
    history_count: int,
) -> tuple[str, pd.DataFrame | None, pd.DataFrame | None, str | None]:
    try:
        df = provider.get_history(code, count=history_count)
        if df is None or len(df) < max(
            int(strategy_params.TREND_PULLBACK_PARAMS.get("slow", 20)) + 3,
            30,
        ):
            return code, df, None, "short_history"
        out = trend_pullback(df, strategy_params.TREND_PULLBACK_PARAMS)
        return code, df, out, None
    except Exception as exc:
        return code, None, None, str(exc)[:200]


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
    parser.add_argument(
        "--roundtrip-cost-bps",
        type=float,
        default=strategy_params.DEFAULT_ROUNDTRIP_COST_BPS,
        help="Estimated roundtrip cost in bps for cost-aware filtering",
    )
    parser.add_argument(
        "--entry-consensus-min",
        type=float,
        default=strategy_params.ENTRY_CONSENSUS_MIN_DEFAULT,
        help="Minimum consensus ratio from robustness grid",
    )
    parser.add_argument(
        "--disable-robust-check",
        action="store_true",
        help="Disable entry robustness check against parameter grid",
    )
    args = parser.parse_args()

    provider = MarketDataProvider()
    universe = provider.get_mainboard_universe(as_of=None, top_n=int(args.top_n))
    if not universe:
        print("ERROR: empty universe", file=sys.stderr)
        sys.exit(1)

    rows: list[tuple[str, pd.DataFrame | None, pd.DataFrame | None, str | None]] = []
    with ThreadPoolExecutor(max_workers=max(1, int(args.workers))) as pool:
        futs = {pool.submit(_scan_one, provider, c, int(args.history_count)): c for c in universe}
        for fut in as_completed(futs):
            rows.append(fut.result())

    param_variants = _build_param_variants(
        strategy_params.TREND_PULLBACK_PARAMS,
        strategy_params.ROBUSTNESS_PARAM_GRID,
    )

    buy_prev_raw: list[dict] = []
    buy_last_raw: list[dict] = []
    buy_prev: list[dict] = []
    buy_last: list[dict] = []
    errors: list[dict] = []

    for code, history_df, enriched, err in rows:
        if err:
            errors.append({"code": code, "error": err})
            continue
        assert enriched is not None
        last = _row_snapshot(enriched, len(enriched) - 1)
        prev = _row_snapshot(enriched, len(enriched) - 2) if len(enriched) >= 2 else None
        if prev and prev.get("entry"):
            consensus_ratio = (
                _entry_consensus_ratio(history_df, param_variants, use_previous_day=True)
                if (history_df is not None and not args.disable_robust_check)
                else 1.0
            )
            edge_after_cost = _edge_after_cost(prev, float(args.roundtrip_cost_bps))
            item = {
                "code": code,
                "signal_bar": prev,
                "asof_bar": last,
                "entry_consensus_ratio": round(consensus_ratio, 4),
                "edge_after_cost": round(edge_after_cost, 6),
                "cost_filter_passed": edge_after_cost > 0,
                "consensus_filter_passed": consensus_ratio >= float(args.entry_consensus_min),
            }
            buy_prev_raw.append(item)
            if item["cost_filter_passed"] and item["consensus_filter_passed"]:
                buy_prev.append(item)
        if last and last.get("entry"):
            consensus_ratio = (
                _entry_consensus_ratio(history_df, param_variants, use_previous_day=False)
                if (history_df is not None and not args.disable_robust_check)
                else 1.0
            )
            edge_after_cost = _edge_after_cost(last, float(args.roundtrip_cost_bps))
            item = {
                "code": code,
                "signal_bar": last,
                "entry_consensus_ratio": round(consensus_ratio, 4),
                "edge_after_cost": round(edge_after_cost, 6),
                "cost_filter_passed": edge_after_cost > 0,
                "consensus_filter_passed": consensus_ratio >= float(args.entry_consensus_min),
            }
            buy_last_raw.append(item)
            if item["cost_filter_passed"] and item["consensus_filter_passed"]:
                buy_last.append(item)

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
        for c, _, en, err in rows:
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
    for _, _, enriched, err in rows:
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
        "roundtrip_cost_bps": float(args.roundtrip_cost_bps),
        "entry_consensus_min": float(args.entry_consensus_min),
        "robust_check_enabled": not bool(args.disable_robust_check),
        "params": strategy_params.TREND_PULLBACK_PARAMS,
        "robustness_param_grid": strategy_params.ROBUSTNESS_PARAM_GRID,
        "todo_confirm_items": strategy_params.TODO_CONFIRM_ITEMS,
        "reference_intraday_stop_pct": strategy_params.REFERENCE_INTRADAY_STOP_PCT,
        "buy": {
            "from_previous_day_close": buy_prev_out,
            "from_last_close": buy_last_out,
            "from_previous_day_close_raw": buy_prev_raw,
            "from_last_close_raw": buy_last_raw,
            "from_previous_day_close_total": len(buy_prev),
            "from_last_close_total": len(buy_last),
            "from_previous_day_close_raw_total": len(buy_prev_raw),
            "from_last_close_raw_total": len(buy_last_raw),
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
