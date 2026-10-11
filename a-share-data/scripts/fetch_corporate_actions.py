#!/usr/bin/env python3
"""Unlock schedules, repurchase progress and disclosed holder changes."""
import argparse
from datetime import datetime, timedelta
import json
import math
import time

try:
    from .data_runtime import cached_fetch
    from .reference_common import stock_identity, iso_date, datacenter, TZ, failed, UpstreamError
except ImportError:
    from data_runtime import cached_fetch
    from reference_common import stock_identity, iso_date, datacenter, TZ, failed, UpstreamError


REPORTS = {
    "unlock": ("RPT_LIFT_STAGE", "SECURITY_CODE", "FREE_DATE"),
    "repurchase": ("RPTA_WEB_GETHGLIST_NEW", "DIM_SCODE", "UPDATEDATE"),
    "holder_changes": ("RPT_SHARE_HOLDER_INCREASE", "SECURITY_CODE", "NOTICE_DATE"),
}
PROGRESS = {"001": "董事会预案", "002": "股东大会通过", "003": "股东大会否决",
            "004": "实施中", "005": "停止实施", "006": "完成实施"}


def query_corporate_actions(kind="unlock", code="", start="", end="", days=30, direction="all",
                            limit=500, max_pages=10, max_seconds=25, no_cache=False):
    if kind not in REPORTS or direction not in ("all", "increase", "decrease"):
        raise ValueError("invalid kind/direction")
    if not 1 <= days <= 366 or not 1 <= limit <= 5000 or not 1 <= max_pages <= 50 or not 1 <= max_seconds <= 30:
        raise ValueError("days=1..366; limit=1..5000; max_pages=1..50; max_seconds=1..30")
    if direction != "all" and kind != "holder_changes":
        raise ValueError("direction applies only to holder_changes")
    identity = stock_identity(code) if code else None
    start, end = iso_date(start), iso_date(end)
    today = datetime.now(TZ).date()
    if not identity and not (start and end):
        if kind == "unlock" and not start and not end:
            start, end = today.isoformat(), (today + timedelta(days=days - 1)).isoformat()
        else:
            raise ValueError("provide code or an explicit bounded start/end window")
    if start and end and start > end:
        raise ValueError("start must not be after end")
    if not identity and (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days > 365:
        raise ValueError("market-wide window cannot exceed 366 days")
    report, stock_field, date_field = REPORTS[kind]
    filters = []
    if identity:
        filters.append(f'({stock_field}="{identity["code"]}")')
    if start:
        filters.append(f"({date_field}>='{start}')")
    if end:
        filters.append(f"({date_field}<='{end} 23:59:59')")
    if direction != "all":
        filters.append(f'(DIRECTION="{"增持" if direction == "increase" else "减持"}")')
    key = f"corporate-v1:{kind}:{identity}:{start}:{end}:{direction}:{limit}:{max_pages}:{max_seconds}"

    def load(_):
        deadline = time.monotonic() + max_seconds
        try:
            raw, meta = datacenter(report, "".join(filters), f"{date_field},{stock_field}", deadline,
                                   min(max_pages, math.ceil(limit / 100)), 100)
            data = []
            for item in raw:
                if identity and str(item.get(stock_field)) != identity["code"]:
                    raise UpstreamError("provider ignored stock filter")
                event_date = str(item.get(date_field) or "")[:10]
                if not event_date or iso_date(event_date) != event_date:
                    raise UpstreamError("event date field missing")
                if (start and event_date < start) or (end and event_date > end):
                    raise UpstreamError("provider ignored requested date window")
                if kind == "holder_changes" and direction != "all":
                    expected = "增持" if direction == "increase" else "减持"
                    if item.get("DIRECTION") != expected:
                        raise UpstreamError("provider ignored change direction")
                row = {"source": "eastmoney_datacenter", "kind": kind,
                       "stock_code": str(item.get(stock_field)), "event_date": event_date, "raw": item}
                if kind == "repurchase":
                    row["progress_label"] = PROGRESS.get(str(item.get("REPURPROGRESS")))
                data.append(row)
            truncated = len(data) > limit
            data = data[:limit]
            meta.update(count=len(data), code=identity["code"] if identity else None, kind=kind,
                        source="Eastmoney datacenter", start=start, end=end, date_basis=date_field,
                        direction=direction, limit=limit,
                        coverage_limited=meta["coverage_limited"] or truncated,
                        raw_units="Unlock share fields: 10,000 shares; no scaling applied." if kind == "unlock" else "Provider-native; no value scaling applied.",
                        notes="Unlock FREE_DATE is scheduled availability; holder NOTICE_DATE is disclosure date. Holder changes do not establish complete future reduction plans. Repurchase progress is the provider enumeration, not inferred from dates.")
            state = "partial" if meta["coverage_limited"] else "ok" if data else "empty"
            return {"status": state, "meta": meta, "data": data}
        except Exception as exc:
            return failed(exc, kind=kind, code=identity["code"] if identity else None,
                          source="Eastmoney datacenter", start=start, end=end, date_basis=date_field)
    result, cache = cached_fetch(key, load, 120, no_cache,
                                 cacheable=lambda value: value["status"] in ("ok", "empty"))
    result["meta"].update(cache)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=list(REPORTS), default="unlock")
    parser.add_argument("--code", default="")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--direction", choices=["all", "increase", "decrease"], default="all")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-seconds", type=float, default=25)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = query_corporate_actions(args.kind, args.code, args.start, args.end, args.days,
                                         args.direction, args.limit, args.max_pages, args.max_seconds, args.no_cache)
    except Exception as exc:
        result = failed(exc)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    if result["status"] == "unavailable":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
