#!/usr/bin/env python3
"""Company concepts and provider-written reasons, retaining every displayed category."""
import argparse
from concurrent.futures import wait
import json
import time

try:
    from .data_runtime import cached_fetch, submit_source
    from .reference_common import stock_identity, request, get_json, now_iso, failed, UpstreamError
except ImportError:
    from data_runtime import cached_fetch, submit_source
    from reference_common import stock_identity, request, get_json, now_iso, failed, UpstreamError


def parse_ths_concepts(html, code):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    identities = [item.get_text(strip=True) for item in soup.select("h1, .stock-code")]
    if code not in identities:
        raise UpstreamError("F10 issuer identity missing or different; refusing inferred identity")
    tables = soup.select("table.gnContent")
    if not tables:
        raise UpstreamError("F10 concept tables absent; page layout or access response changed")
    rows, categories = [], []
    for table in tables:
        heading = table.find_previous(["h2", "h3"])
        category = heading.get_text(" ", strip=True) if heading else None
        count = 0
        trs = table.find_all("tr")
        for index, tr in enumerate(trs):
            name_cell = tr.select_one("td.gnName, td.gnStockList")
            if name_cell is None:
                continue
            detail = trs[index + 1] if index + 1 < len(trs) and len(trs[index + 1].find_all("td", recursive=False)) == 1 else None
            reason_cell = detail.find("td") if detail else tr.select_one("td.wider")
            reason = reason_cell.get_text(" ", strip=True) if reason_cell else None
            name = name_cell.get_text(" ", strip=True)
            if not name:
                raise UpstreamError("empty concept name in displayed category")
            rows.append({"stock_code": code, "concept_code": name_cell.get("clid"), "name": name,
                         "category": category, "reason": reason, "evidence_date": None,
                         "source": "ths_f10", "url": f"https://basic.10jqka.com.cn/{code}/concept.html",
                         "raw": {"name_html": str(name_cell), "row_html": str(tr),
                                 "reason_html": str(reason_cell) if reason_cell else None}})
            count += 1
        # A non-empty data table that no longer has recognizable name cells must not look empty.
        if table.find("td") and count == 0:
            raise UpstreamError("unrecognized concept category layout")
        categories.append({"category": category, "count": count})
    return rows, {"categories": categories, "tables_parsed": len(tables), "identity_verified": True,
                  "coverage_scope": "all displayed F10 concept tables; not a historical membership archive",
                  "coverage_limited": False, "taxonomy": "THS concepts and F10 topic labels"}


def ths_concepts(identity, deadline):
    code = identity["code"]
    response = request(f"https://basic.10jqka.com.cn/{code}/concept.html", deadline,
                       referer="https://basic.10jqka.com.cn/")
    # F10 declares GBK in its HTML while HTTP may omit charset. Preserve its text correctly.
    html = response.content.decode("gbk")
    return parse_ths_concepts(html, code)


def eastmoney_concepts(identity, deadline, max_pages):
    rows, total, pages, fetched, errors = [], None, None, 0, []
    for page in range(1, max_pages + 1):
        params = {"reportName": "RPT_F10_CORETHEME_BOARDTYPE", "columns": "ALL",
                  "filter": f'(SECUCODE="{identity["secu_code"]}")(IS_PRECISE="1")',
                  "sortColumns": "BOARD_RANK", "sortTypes": "1", "pageNumber": page,
                  "pageSize": 50, "source": "HSF10", "client": "PC"}
        try:
            obj = get_json("https://datacenter.eastmoney.com/securities/api/data/v1/get", deadline, params=params)
            if obj.get("success") is not True:
                raise UpstreamError(f"API {obj.get('code')}: {obj.get('message')}")
            result = obj.get("result")
            if result is None and page == 1:
                total, pages = 0, 0
                break
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise UpstreamError("Eastmoney concept row schema changed")
            total, pages = int(result["count"]), int(result["pages"])
            for item in result["data"]:
                if str(item.get("SECURITY_CODE")) != identity["code"] or not item.get("BOARD_NAME"):
                    raise UpstreamError("concept issuer filter or name invalid")
                rows.append({"stock_code": identity["code"], "concept_code": item.get("NEW_BOARD_CODE"),
                             "name": item["BOARD_NAME"], "reason": item.get("SELECTED_BOARD_REASON"),
                             "category": "provider_precise_concepts", "evidence_date": None,
                             "source": "eastmoney_f10", "raw": item})
            fetched += 1
            if page >= pages or len(rows) >= total:
                break
        except Exception as exc:
            if not rows:
                raise
            errors.append(f"{type(exc).__name__}: {exc}")
            break
    return rows, {"total": total, "pages_fetched": fetched, "upstream_pages": pages,
                  "coverage_limited": total is None or len(rows) < total or bool(errors), "errors": errors,
                  "coverage_scope": "Eastmoney IS_PRECISE=1 only", "taxonomy": "Eastmoney precise concepts"}


def query_stock_concepts(code, source="all", max_pages=5, max_seconds=20, no_cache=False):
    identity = stock_identity(code)
    if source not in ("all", "ths", "eastmoney") or not 1 <= max_pages <= 20 or not 1 <= max_seconds <= 30:
        raise ValueError("source=all/ths/eastmoney; max_pages=1..20; max_seconds=1..30")
    key = f"stock-concepts-v1:{identity['secu_code']}:{source}:{max_pages}:{max_seconds}"

    def load(_):
        deadline = time.monotonic() + max_seconds
        jobs = {}
        if source in ("all", "ths"):
            jobs["ths_f10"] = lambda: ths_concepts(identity, deadline)
        if source in ("all", "eastmoney"):
            jobs["eastmoney_f10"] = lambda: eastmoney_concepts(identity, deadline, max_pages)
        # Two independent sources only; their classifications are not merged or deduplicated.
        def worker(name, fn):
            started = time.monotonic()
            try:
                data, meta = fn()
                state = "partial" if meta.get("coverage_limited") else "ok" if data else "empty"
                return data, dict(meta, source=name, status=state, count=len(data), elapsed_sec=round(time.monotonic()-started, 3))
            except Exception as exc:
                return [], {"source": name, "status": "unavailable", "error": f"{type(exc).__name__}: {exc}", "elapsed_sec": round(time.monotonic()-started, 3)}
        futures = {submit_source(lambda name=name, fn=fn: worker(name, fn)): name for name, fn in jobs.items()}
        done, pending = wait(futures, timeout=max_seconds)
        data, diagnostics = [], []
        for future in done:
            records, diagnostic = future.result()
            data.extend(records); diagnostics.append(diagnostic)
        for future in pending:
            future.cancel()
            diagnostics.append({"source": futures[future], "status": "timeout", "error": "overall deadline exceeded"})
        diagnostics.sort(key=lambda item: item["source"])
        data.sort(key=lambda item: (item["source"], item.get("category") or "", item["name"]))
        failed_sources = any(item["status"] in ("partial", "unavailable", "timeout") for item in diagnostics)
        available = any(item["status"] in ("ok", "empty", "partial") for item in diagnostics)
        status = "partial" if failed_sources and available else "unavailable" if failed_sources else "ok" if data else "empty"
        return {"status": status, "code": identity["code"], "data": data, "meta": {
            "count": len(data), "sources": diagnostics, "coverage_limited": any(item.get("coverage_limited", item["status"] in ("unavailable", "timeout")) for item in diagnostics),
            "notes": "Provider-written reasons; evidence dates remain unknown. Different taxonomies/categories are retained without semantic filtering or deduplication."}}
    result, cache = cached_fetch(key, load, 300, no_cache, cacheable=lambda value: value["status"] in ("ok", "empty"))
    result["meta"].update(cache)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", required=True)
    parser.add_argument("--source", choices=["all", "ths", "eastmoney"], default="all")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-seconds", type=float, default=20)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = query_stock_concepts(args.code, args.source, args.max_pages, args.max_seconds, args.no_cache)
    except Exception as exc:
        result = failed(exc)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    if result["status"] == "unavailable":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
