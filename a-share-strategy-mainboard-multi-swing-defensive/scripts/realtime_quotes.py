#!/usr/bin/env python3
"""Batch realtime-style quotes using MarketDataProvider (Tencent + minute aggregation)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from paper_trading.market_data import MarketDataProvider


def _normalize_code_token(raw: str) -> str | None:
    s = raw.strip()
    if not s or s.startswith("#"):
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 6:
        return digits[-6:].zfill(6)
    return None


def _load_codes_from_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        c = _normalize_code_token(line)
        if c:
            out.append(c)
    return out


def _fetch_one(
    provider: MarketDataProvider,
    code: str,
    intraday: bool,
    intraday_freq: str,
    intraday_count: int,
) -> dict:
    q = provider.get_quote(code)
    row: dict = {"ok": True, "quote": asdict(q)}
    if intraday:
        try:
            df = provider.get_intraday_bars(code, freq=intraday_freq, count=max(2, intraday_count))
            if df is not None and not df.empty:
                last = df.iloc[-1]
                t = last["time"]
                row["last_intraday_bar"] = {
                    "time": t.strftime("%Y-%m-%d %H:%M:%S") if hasattr(t, "strftime") else str(t),
                    "open": float(last["open"]),
                    "high": float(last["high"]),
                    "low": float(last["low"]),
                    "close": float(last["close"]),
                    "volume": int(last["volume"]),
                    "freq": intraday_freq,
                }
            else:
                row["last_intraday_bar"] = None
        except Exception as exc:
            row["last_intraday_bar_error"] = str(exc)[:120]
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch realtime-style quotes for A-share codes")
    parser.add_argument(
        "codes",
        nargs="*",
        help="6-digit stock codes, space-separated",
    )
    parser.add_argument(
        "-f",
        "--file",
        type=Path,
        default=None,
        help="File with one code per line (# comments allowed)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Single JSON object to stdout",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel workers when multiple codes",
    )
    parser.add_argument(
        "--intraday",
        action="store_true",
        help="Also fetch last intraday K bar (extra request per code)",
    )
    parser.add_argument(
        "--intraday-freq",
        default="5m",
        choices=["1m", "5m", "15m", "30m", "60m"],
        help="Intraday bar frequency when --intraday",
    )
    parser.add_argument(
        "--intraday-count",
        type=int,
        default=48,
        help="How many intraday bars to pull before taking the last (min 2)",
    )
    args = parser.parse_args()

    codes: list[str] = []
    for c in args.codes:
        norm = _normalize_code_token(c)
        if norm:
            codes.append(norm)
    if args.file:
        codes.extend(_load_codes_from_file(args.file))
    seen: set[str] = set()
    deduped: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    codes = deduped

    if not codes:
        print("ERROR: no codes (pass codes as args or --file)", file=sys.stderr)
        sys.exit(2)

    provider = MarketDataProvider()
    workers = min(max(1, int(args.workers)), len(codes))
    results: list[dict] = []
    errors: list[dict] = []

    def task(code: str) -> tuple[str, dict]:
        try:
            payload = _fetch_one(
                provider,
                code,
                bool(args.intraday),
                str(args.intraday_freq),
                int(args.intraday_count),
            )
            return code, payload
        except Exception as exc:
            return code, {"ok": False, "code": code, "error": str(exc)[:200]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(task, c): c for c in codes}
        for fut in as_completed(futs):
            _code, payload = fut.result()
            if payload.get("ok"):
                results.append(payload)
            else:
                errors.append(payload)

    results.sort(key=lambda x: str(x.get("quote", {}).get("symbol", "")))

    out_obj = {
        "count": len(results),
        "quotes": [r["quote"] for r in results if r.get("quote")],
        "details": results,
        "errors": errors,
    }

    if args.json:
        print(json.dumps(out_obj, ensure_ascii=False, indent=2))
        return

    print("count", len(results), "errors", len(errors))
    for r in results:
        q = r.get("quote")
        if not q:
            continue
        sym = q.get("symbol", "")
        name = q.get("name", "")
        print(
            sym,
            name,
            "price",
            q.get("price"),
            "chg%",
            q.get("change_pct"),
            "vol",
            q.get("volume"),
            "time",
            q.get("timestamp"),
            q.get("source", ""),
        )
        if r.get("last_intraday_bar"):
            b = r["last_intraday_bar"]
            print("   intraday", b.get("freq"), "last", b.get("time"), "close", b.get("close"))
    for e in errors:
        print("ERR", e.get("code"), e.get("error"))


if __name__ == "__main__":
    main()
