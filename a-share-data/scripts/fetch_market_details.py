#!/usr/bin/env python3
"""Provider-native limit-up/broken-board pools and Dragon-Tiger buy/sell seats."""
import argparse
from concurrent.futures import wait
from datetime import datetime
import json
import time

try:
    from .data_runtime import cached_fetch, submit_source
    from .reference_common import stock_identity, iso_date, get_json, datacenter, TZ, failed, UpstreamError
except ImportError:
    from data_runtime import cached_fetch, submit_source
    from reference_common import stock_identity, iso_date, get_json, datacenter, TZ, failed, UpstreamError


POOL_ROUTES = {"up": ("getTopicZTPool", "limit_up_pool"),
               "broken": ("getTopicZBPool", "open_limit_pool")}
THS_FIELDS = "199112,10,9001,330323,330324,330325,9002,330329,133971,133970,1968584,3475914,513070,513071,3541450,3642053,3541451"


def _eastmoney_pool(kind, date, deadline, max_pages):
    obj = get_json("https://push2ex.eastmoney.com/" + POOL_ROUTES[kind][0], deadline,
                   params={"ut": "7eea3edcaed734bea9cbfc24409ed989", "dpt": "wz.ztzt",
                           "Pageindex": 0, "pagesize": 10000, "sort": "fbt:asc", "date": date.replace("-", "")},
                   referer="https://quote.eastmoney.com/")
    if obj.get("rc") != 0:
        raise UpstreamError(f"pool API rc={obj.get('rc')}")
    data = obj.get("data")
    if data is None:
        return [], {"source": "eastmoney", "trade_date": None, "total": 0, "pages_fetched": 1,
                    "coverage_limited": False, "coverage_scope": "all A-share markets", "market": "all",
                    "date_verified": False, "empty_reason": "provider has no pool snapshot for this request"}
    if not isinstance(data, dict) or not isinstance(data.get("pool"), list):
        raise UpstreamError("pool response schema changed")
    latest = iso_date(data.get("qdate"))
    if not latest:
        raise UpstreamError("pool qdate absent")
    rows, total = data["pool"], int(data["tc"])
    for row in rows:
        stock_identity(row.get("c"))
        if not row.get("n"):
            raise UpstreamError("pool stock name absent")
    # qdate is the latest market day even on historical responses. It cannot
    # identify the historical pool date. Verify history against dated THS rows;
    # verify a future/non-trading fallback against the actual latest EM snapshot.
    actual, check = None, {"source": "eastmoney_qdate", "status": "ok"}
    if not rows and date != latest:
        check = {"status": "not_available", "method": "no rows; historical snapshot availability unknown"}
    elif date == latest:
        actual = date
    else:
        try:
            if date < latest:
                control, control_meta = _ths_pool(kind, date, deadline, max_pages)
                shsz = {str(row["c"]) for row in rows if stock_identity(row["c"])["market"] != "BJ"}
                if not shsz or control_meta["coverage_limited"] or control_meta["trade_date"] != date or shsz != {str(row["code"]) for row in control}:
                    raise UpstreamError("dated THS SH/SZ membership does not confirm historical EM pool")
                actual = date
                check = {"source": "ths_dated_pool", "status": "ok", "method": "complete SH/SZ code-set and THS row-date match", "market": "shsz"}
            else:
                control, control_meta = _eastmoney_pool(kind, latest, deadline, max_pages)
                fingerprint = lambda values: sorted(json.dumps(value, sort_keys=True) for value in values)
                if control_meta["coverage_limited"] or fingerprint(rows) != fingerprint(control):
                    raise UpstreamError("response does not match the latest dated EM snapshot")
                actual = latest
                check = {"source": "eastmoney_latest_pool", "status": "ok", "method": "full raw-record match"}
        except Exception as exc:
            check = {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
    return rows, {"source": "eastmoney", "trade_date": actual, "provider_qdate": latest,
                  "provider_meta": {key: value for key, value in data.items() if key != "pool"},
                  "date_check": check, "total": total, "pages_fetched": 1,
                  "coverage_limited": len(rows) != total or (bool(rows) and actual is None), "coverage_scope": "all A-share markets", "market": "all",
                  "date_verified": actual is not None, "raw_units": "p: 0.001 CNY; fbt/lbt: HHMMSS integer; other fields unchanged"}


def _ths_pool(kind, date, deadline, max_pages):
    rows, total, actual, fetched, errors = [], None, None, 0, []
    for page in range(1, max_pages + 1):
        try:
            obj = get_json("https://data.10jqka.com.cn/dataapi/limit_up/" + POOL_ROUTES[kind][1], deadline,
                           params={"page": page, "limit": 200, "field": THS_FIELDS, "filter": "HS,GEM2STAR",
                                   "order_field": "330324", "order_type": 0, "date": date.replace("-", "")},
                           referer="https://data.10jqka.com.cn/")
            if obj.get("status_code") != 0:
                raise UpstreamError(f"THS API {obj.get('status_code')}: {obj.get('status_msg')}")
            data = obj.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("info"), list):
                raise UpstreamError("THS pool schema changed")
            page_date = iso_date(data.get("date"))
            if not page_date or (actual and page_date != actual):
                raise UpstreamError("THS pagination trade date missing or inconsistent")
            actual = page_date
            total = int(data["page"]["total"])
            batch = data["info"]
            for row in batch:
                identity = stock_identity(row.get("code"))
                if identity["market"] == "BJ":
                    raise UpstreamError("THS returned a stock outside its declared SH/SZ scope")
                for field in ("first_limit_up_time", "last_limit_up_time"):
                    if row.get(field):
                        row_date = datetime.fromtimestamp(float(row[field]), TZ).date().isoformat()
                        if row_date != actual:
                            raise UpstreamError("THS row timestamp differs from pool trade date")
            rows.extend(batch)
            fetched += 1
            if len(rows) >= total:
                break
            if not batch:
                raise UpstreamError("THS empty page before advertised end")
        except Exception as exc:
            if not rows:
                raise
            errors.append(f"{type(exc).__name__}: {exc}")
            break
    return rows, {"source": "ths", "trade_date": actual, "total": total, "pages_fetched": fetched,
                  "coverage_limited": total is None or len(rows) != total or bool(errors), "errors": errors,
                  "coverage_scope": "Shanghai/Shenzhen only (HS,GEM2STAR); excludes Beijing", "market": "shsz",
                  "date_verified": actual is not None, "raw_units": "Provider-native; time fields are Unix seconds"}


def query_market_pool(kind="up", date="", source="auto", market="all", limit=500,
                      max_pages=10, max_seconds=20, allow_date_fallback=False,
                      allow_partial_scope=False, no_cache=False):
    if kind not in POOL_ROUTES or source not in ("auto", "eastmoney", "ths") or market not in ("all", "shsz"):
        raise ValueError("kind=up/broken; source=auto/eastmoney/ths; market=all/shsz")
    if not 1 <= limit <= 5000 or not 1 <= max_pages <= 50 or not 1 <= max_seconds <= 30:
        raise ValueError("limit=1..5000; max_pages=1..50; max_seconds=1..30")
    if source == "ths" and market == "all" and not allow_partial_scope:
        raise ValueError("THS covers SH/SZ only: select market=shsz or allow_partial_scope")
    explicit_date = bool(date)
    requested = iso_date(date) if date else datetime.now(TZ).date().isoformat()
    key = f"market-pool-v1:{kind}:{requested}:{explicit_date}:{source}:{market}:{limit}:{max_pages}:{max_seconds}:{allow_date_fallback}:{allow_partial_scope}"

    def load(_):
        deadline = time.monotonic() + max_seconds
        routes = ["eastmoney", "ths"] if source == "auto" and (market == "shsz" or allow_partial_scope) else ["eastmoney"] if source == "auto" else [source]
        attempts = []
        for provider in routes:
            started = time.monotonic()
            try:
                rows, meta = (_eastmoney_pool if provider == "eastmoney" else _ths_pool)(kind, requested, deadline, max_pages)
                actual = meta["trade_date"]
                mismatch = bool(actual and actual != requested)
                if mismatch and explicit_date and not allow_date_fallback:
                    raise UpstreamError(f"requested {requested}, provider returned {actual}; enable allow_date_fallback to accept")
                # Code filtering is solely an explicit market scope option; raw records are retained.
                selected = rows if market == "all" else [row for row in rows if stock_identity(row["c" if provider == "eastmoney" else "code"])["market"] != "BJ"]
                scope_limited = market == "all" and meta["market"] != "all"
                limited = meta["coverage_limited"] or scope_limited or len(selected) > limit
                attempts.append({"source": provider, "status": "partial" if meta["coverage_limited"] else "ok" if rows else "empty", "elapsed_sec": round(time.monotonic() - started, 3)})
                data = [{"stock_code": str(row["c" if provider == "eastmoney" else "code"]),
                         "source": provider, "trade_date": actual, "raw": row} for row in selected[:limit]]
                provider_market = meta["market"]
                if market == "shsz":
                    meta.update(market="shsz", coverage_scope="Shanghai/Shenzhen only; excludes Beijing")
                meta.update(kind=kind, requested_date=requested, date_fallback=mismatch, date_explicit=explicit_date,
                            provider_market=provider_market,
                            requested_market=market, scope_limited=scope_limited, coverage_limited=limited,
                            selected_total=len(selected), count=len(data), limit=limit, source_attempts=attempts)
                return {"status": "partial" if limited else "ok" if data else "empty", "meta": meta, "data": data}
            except Exception as exc:
                attempts.append({"source": provider, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}", "elapsed_sec": round(time.monotonic() - started, 3)})
        return failed(UpstreamError("all permitted pool sources unavailable"), kind=kind, requested_date=requested,
                      requested_market=market, source_attempts=attempts, trade_date=None)

    result, cache = cached_fetch(key, load, 30, no_cache, cacheable=lambda value: value["status"] in ("ok", "empty"))
    result["meta"].update(cache)
    return result


def query_lhb_seats(code, date, max_pages=10, max_seconds=20, no_cache=False):
    identity, actual = stock_identity(code), iso_date(date)
    if not actual or not 1 <= max_pages <= 50 or not 1 <= max_seconds <= 30:
        raise ValueError("date required; max_pages=1..50; max_seconds=1..30")
    key = f"lhb-seats-v1:{identity['code']}:{actual}:{max_pages}:{max_seconds}"

    def load(_):
        deadline = time.monotonic() + max_seconds
        filter_ = f'(SECURITY_CODE="{identity["code"]}")(TRADE_DATE=\'{actual}\')'

        def side_query(side):
            started = time.monotonic()
            try:
                # Current AKShare protocol uses BUY/SELL, not the obsolete *_AMT_REAL fields.
                rows, meta = datacenter("RPT_BILLBOARD_DAILYDETAILS" + side.upper(), filter_, side.upper(), deadline, max_pages)
                records = []
                for row in rows:
                    if str(row.get("SECURITY_CODE")) != identity["code"] or str(row.get("TRADE_DATE", ""))[:10] != actual:
                        raise UpstreamError("seat issuer/date filter ignored")
                    if any(field not in row for field in ("BUY", "SELL", "NET", "OPERATEDEPT_NAME", "EXPLANATION")):
                        raise UpstreamError("seat fields changed")
                    records.append({"source": "eastmoney_datacenter", "side": side, "stock_code": identity["code"],
                                    "trade_date": actual, "raw": row})
                meta.update(side=side, status="partial" if meta["coverage_limited"] else "ok" if records else "empty", count=len(records), elapsed_sec=round(time.monotonic()-started, 3))
                return records, meta
            except Exception as exc:
                return [], {"side": side, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
        futures = {submit_source(lambda side=side: side_query(side)): side for side in ("buy", "sell")}
        done, pending = wait(futures, timeout=max_seconds)
        data, diagnostics = [], []
        for future in done:
            rows, meta = future.result()
            data.extend(rows); diagnostics.append(meta)
        for future in pending:
            future.cancel()
            diagnostics.append({"side": futures[future], "status": "unavailable", "error": "overall deadline exceeded"})
        diagnostics.sort(key=lambda item: item["side"])
        data.sort(key=lambda item: (item["side"], -float(item["raw"][item["side"].upper()] or 0)))
        incomplete = any(item["status"] in ("partial", "unavailable") for item in diagnostics)
        state = "partial" if incomplete and data else "unavailable" if incomplete else "ok" if data else "empty"
        return {"status": state, "meta": {"code": identity["code"], "trade_date": actual, "source": "Eastmoney datacenter",
                "coverage_limited": incomplete, "sides": diagnostics, "count": len(data), "raw_units": "BUY/SELL/NET: CNY; TOTAL_BUYRIO/TOTAL_SELLRIO: percent",
                "notes": "Preserves EXPLANATION and TRADE_ID; the same seat may appear for multiple listing reasons. No cross-reason deduplication."}, "data": data}

    result, cache = cached_fetch(key, load, 120, no_cache, cacheable=lambda value: value["status"] in ("ok", "empty"))
    result["meta"].update(cache)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pool", choices=list(POOL_ROUTES))
    group.add_argument("--seats", metavar="CODE")
    parser.add_argument("--date", default="")
    parser.add_argument("--source", choices=["auto", "eastmoney", "ths"], default="auto")
    parser.add_argument("--market", choices=["all", "shsz"], default="all")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-seconds", type=float, default=20)
    parser.add_argument("--allow-date-fallback", action="store_true")
    parser.add_argument("--allow-partial-scope", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.seats:
            if args.source != "auto" or args.market != "all" or args.limit != 500 or args.allow_date_fallback or args.allow_partial_scope:
                raise ValueError("source/market/limit/fallback flags apply only to pools")
            result = query_lhb_seats(args.seats, args.date, args.max_pages, args.max_seconds, args.no_cache)
        else:
            result = query_market_pool(args.pool, args.date, args.source, args.market, args.limit,
                                       args.max_pages, args.max_seconds, args.allow_date_fallback, args.allow_partial_scope, args.no_cache)
    except Exception as exc:
        result = failed(exc)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    if result["status"] == "unavailable":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
