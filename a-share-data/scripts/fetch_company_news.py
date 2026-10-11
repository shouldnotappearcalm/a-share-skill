#!/usr/bin/env python3
"""Recent company news and disclosures, with dates, links and source diagnostics.

Requires requests only. CNINFO disclosures and Eastmoney disclosures/news are
queried independently within one deadline. News snippets are not full articles.
"""
import argparse
import hashlib
import html
import json
import os
import queue
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Shanghai")
CACHE = Path(__file__).resolve().parent.parent / "cache" / "company_news"
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.cninfo.com.cn/"}
_HTTP = threading.local()
CACHE_SCHEMA = 2


def http_session():
    if not hasattr(_HTTP, "session"):
        _HTTP.session = requests.Session()
    return _HTTP.session


def normalize_code(value):
    code = value.strip().upper()
    code = re.sub(r"^(SH|SZ|BJ)\.?", "", code)
    code = re.sub(r"\.(XSHG|XSHE|SH|SZ|BJ)$", "", code)
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("股票代码必须为六位数字，或带 SH/SZ/BJ、XSHG/XSHE 前后缀")
    return code


def clean(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(value or "")))).strip()


def parse_time(value):
    try:
        if isinstance(value, (float, int)):
            return datetime.fromtimestamp(value / 1000, TZ)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)
    except (TypeError, ValueError, OverflowError):
        return None


def request(method, url, deadline, cache_ttl=300, **kwargs):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("整体查询时间预算已耗尽")
    key = hashlib.sha256(json.dumps([CACHE_SCHEMA, method, url, kwargs.get("params"), kwargs.get("data")], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = CACHE / "http" / (key + ".json")
    cached = None if getattr(_HTTP, "no_cache", False) or not cache_ttl else load_cache(path, cache_ttl)
    if cached is not None:
        _HTTP.cache_hits = getattr(_HTTP, "cache_hits", 0) + 1
        fetched_at = datetime.fromtimestamp(path.stat().st_mtime, TZ).isoformat()
        _HTTP.fetch_times = getattr(_HTTP, "fetch_times", []) + [fetched_at]
        response = requests.Response()
        response.status_code = 200
        response.encoding = "utf-8"
        response._content = cached.encode("utf-8")
        return response
    # One retry for transient connection/TLS failures, within the same deadline.
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("整体查询时间预算已耗尽")
        try:
            _HTTP.requests = getattr(_HTTP, "requests", 0) + 1
            response = http_session().request(method, url, timeout=min(6, remaining), **kwargs)
            break
        except (requests.ConnectionError, requests.Timeout):
            if attempt:
                raise
    response.raise_for_status()
    _HTTP.fetch_times = getattr(_HTTP, "fetch_times", []) + [datetime.now(TZ).isoformat()]
    if cache_ttl and not getattr(_HTTP, "no_cache", False):
        # Do not make an HTML error page or malformed JSON sticky for five minutes.
        text = response.text.strip()
        try:
            obj = json.loads(text if text.startswith(("{", "[")) else text[text.index("(") + 1:text.rindex(")")])
            if not isinstance(obj, dict) or not obj.get("error"):
                save_cache(path, response.text)
        except (ValueError, TypeError):
            pass
    return response


def load_cache(path, ttl):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if 0 <= time.time() - payload["saved_at"] < ttl:
            return payload["data"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def save_cache(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"saved_at": time.time(), "data": data}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def resolve_name(code, deadline):
    market = "sh" if code.startswith("6") else "bj" if code.startswith(("4", "8", "9")) else "sz"
    try:
        text = request("GET", f"https://qt.gtimg.cn/q={market}{code}", deadline).text
        parts = text.split("~")
        if len(parts) > 2 and parts[2] == code:
            return parts[1]
    except Exception:
        pass
    return ""


def news_em(keyword, deadline, pages, start=None):
    rows, truncated = [], False
    for page in range(1, pages + 1):
        param = {"uid": "", "keyword": keyword, "type": ["cmsArticleWebOld"],
                 "client": "web", "clientType": "web", "clientVersion": "curr",
                 "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time",
                           "pageIndex": page, "pageSize": 50, "preTag": "", "postTag": ""}}}
        response = request("GET", "https://search-api-web.eastmoney.com/search/jsonp", deadline,
                           params={"cb": "jQuery", "param": json.dumps(param, ensure_ascii=False)},
                           headers={"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"})
        text = response.text.strip()
        obj = json.loads(text if text.startswith("{") else text[text.index("(") + 1:text.rindex(")")])
        batch = obj.get("result", {}).get("cmsArticleWebOld")
        if not isinstance(batch, list):
            raise ValueError("东方财富新闻响应结构变化")
        for row in batch:
            rows.append({"kind": "news", "title": clean(row.get("title")),
                         "summary": clean(row.get("content")), "published_at": row.get("date"),
                         "publisher": clean(row.get("mediaName")), "provider": "eastmoney_news",
                         "url": row.get("url") or (f"https://finance.eastmoney.com/a/{row['code']}.html" if row.get("code") else "")})
        truncated = len(batch) >= 50
        stamps = [parse_time(row.get("published_at")) for row in rows]
        if start and any(stamp and stamp < start for stamp in stamps):
            truncated = False
            break
        if not truncated:
            break
    return rows, truncated


def announcements_em(code, deadline, pages, start=None):
    rows, truncated = [], False
    for page in range(1, pages + 1):
        obj = request("GET", "https://np-anotice-stock.eastmoney.com/api/security/ann", deadline,
                      params={"sr": "-1", "page_size": 100, "page_index": page,
                              "ann_type": "A", "client_source": "web", "stock_list": code},
                      headers={"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}).json()
        batch = (obj.get("data") or {}).get("list")
        if not isinstance(batch, list):
            raise ValueError("东方财富公告响应结构变化")
        for row in batch:
            if not any(str(c.get("stock_code")) == code for c in row.get("codes", [])):
                continue
            art = row.get("art_code")
            rows.append({"kind": "announcement", "title": clean(row.get("title")), "summary": "",
                         "published_at": str(row.get("notice_date", ""))[:10],
                         "publisher": "上市公司公告", "provider": "eastmoney_announcements",
                         "source_categories": [c.get("column_name") for c in row.get("columns", []) if c.get("column_name")],
                         "url": f"https://data.eastmoney.com/notices/detail/{code}/{art}.html" if art else ""})
        truncated = len(batch) >= 100
        stamps = [parse_time(row.get("published_at")) for row in rows]
        if start and any(stamp and stamp < start for stamp in stamps):
            truncated = False
            break
        if not truncated:
            break
    return rows, truncated


def announcements_cninfo(code, start, end, deadline, pages):
    path = CACHE / "cninfo_companies.json"
    mapping = load_cache(path, 7 * 86400)
    if mapping is None or code not in mapping:
        obj = request("GET", "https://www.cninfo.com.cn/new/data/szse_stock.json", deadline, headers=HEADERS).json()
        mapping = {s["code"]: s["orgId"] for s in obj["stockList"]}
        save_cache(path, mapping)
    if code not in mapping:
        raise ValueError(f"巨潮代码映射未收录 {code}")
    rows, truncated = [], False
    for page in range(1, pages + 1):
        obj = request("POST", "https://www.cninfo.com.cn/new/hisAnnouncement/query", deadline,
                      data={"pageNum": page, "pageSize": 30, "column": "szse", "tabName": "fulltext",
                            "stock": f"{code},{mapping[code]}", "seDate": f"{start}~{end}",
                            "sortName": "time", "sortType": "desc", "isHLtitle": "false"}, headers=HEADERS).json()
        batch = obj.get("announcements")
        if batch is None and obj.get("totalAnnouncement") == 0:
            batch = []
        if not isinstance(batch, list):
            raise ValueError("巨潮公告响应结构变化")
        for row in batch:
            if str(row.get("secCode")) != code:
                continue
            adjunct = row.get("adjunctUrl", "")
            url = "https://static.cninfo.com.cn/" + adjunct.lstrip("/") if adjunct else "https://www.cninfo.com.cn/new/disclosure/detail?" + urlencode({"stockCode": code, "announcementId": row.get("announcementId"), "orgId": row.get("orgId")})
            rows.append({"kind": "announcement", "title": clean(row.get("announcementTitle")),
                         "summary": "", "published_at": row.get("announcementTime"),
                         "publisher": clean(row.get("secName")) or "上市公司公告", "provider": "cninfo", "url": url})
        truncated = bool(obj.get("hasMore")) or obj.get("totalAnnouncement", 0) > page * 30
        if not truncated:
            break
    return rows, truncated


def normalize_items(rows, code, name, start, end, title_only=False):
    output, seen = [], set()
    # CNINFO preferred when disclosures share title/date across providers.
    for row in sorted(rows, key=lambda r: r["provider"] != "cninfo"):
        stamp = parse_time(row.get("published_at"))
        if stamp is None or not start <= stamp <= end or not row.get("title") or not row.get("url"):
            continue
        # Once a company name is known, a bare code alone is ambiguous (e.g.
        # 000001 also appears in stories about the Shanghai Composite index).
        tokens = [name.replace(" ", "")] if name else [code]
        title = row["title"].replace(" ", "")
        body = row.get("summary", "").replace(" ", "")
        match = "security_code" if row["kind"] == "announcement" else "title" if any(t in title for t in tokens) else "summary" if any(t in body for t in tokens) else "upstream_query"
        if title_only and row["kind"] == "news" and match != "title":
            continue
        # Remove company prefix, HTML highlights and punctuation for syndication duplicates.
        normalized_title = re.sub(r"[\W_]+", "", row["title"].removeprefix(name).lstrip(":："))
        key = (row["kind"], stamp.date().isoformat(), normalized_title)
        url_key = (row["kind"], row["url"].replace("http://", "https://"))
        if key in seen or url_key in seen:
            continue
        seen.update([key, url_key])
        row = dict(row, published_at=stamp.isoformat(), matched_in=match)
        row.setdefault("source_categories", [])
        output.append(row)
    return sorted(output, key=lambda r: r["published_at"], reverse=True)


def build_payload(code, name="", days=7, limit=20, max_seconds=20, pages=2, scope="all", no_cache=False, now=None, include_mentions=True, title_only=False):
    code = normalize_code(code)
    now = now or datetime.now(TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    now = now.astimezone(TZ)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    deadline = time.monotonic() + max_seconds
    cache_key = hashlib.sha256(json.dumps([CACHE_SCHEMA, code, name, start.isoformat(), now.date().isoformat(), limit, pages, scope, title_only], ensure_ascii=False).encode()).hexdigest()
    cache_path = CACHE / (cache_key + ".json")
    cached = None if no_cache else load_cache(cache_path, 300)
    if cached:
        cached["meta"]["cache_hit"] = True
        cached["meta"]["queried_at"] = now.isoformat()
        return cached
    name = name.strip() or resolve_name(code, min(deadline, time.monotonic() + 3))
    jobs = {}
    if scope in ("all", "news"):
        for keyword in dict.fromkeys([code] + ([name] if name else [])):
            jobs["eastmoney_news:" + keyword] = (news_em, (keyword, deadline, pages, start))
    if scope in ("all", "announcements"):
        jobs["cninfo"] = (announcements_cninfo, (code, start.date().isoformat(), now.date().isoformat(), deadline, pages))
        jobs["eastmoney_announcements"] = (announcements_em, (code, deadline, pages, start))
    completed = queue.Queue()

    def run(source, fn, args):
        started = time.monotonic()
        _HTTP.no_cache = no_cache
        _HTTP.requests, _HTTP.cache_hits = 0, 0
        _HTTP.fetch_times = []
        try:
            rows, truncated = fn(*args)
            diagnostic = {"source": source, "status": "ok" if rows else "empty", "fetched": len(rows), "truncated": truncated}
        except Exception as exc:
            rows = []
            diagnostic = {"source": source, "status": "error", "fetched": 0, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}
        diagnostic.update({"network_requests": _HTTP.requests, "cache_hits": _HTTP.cache_hits})
        diagnostic["fetched_at"] = min(_HTTP.fetch_times) if _HTTP.fetch_times else None
        diagnostic["elapsed_sec"] = round(time.monotonic() - started, 2)
        completed.put((source, rows, diagnostic))

    for source, (fn, args) in jobs.items():
        threading.Thread(target=run, args=(source, fn, args), daemon=True).start()
    rows, diagnostics, pending = [], [], set(jobs)
    while pending:
        try:
            source, batch, diagnostic = completed.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            break
        pending.remove(source)
        rows.extend(batch)
        diagnostics.append(diagnostic)
    diagnostics += [{"source": source, "status": "timeout", "fetched": 0, "error": "整体查询超时"} for source in sorted(pending)]
    items = normalize_items(rows, code, name, start, now, title_only)
    errors = [d for d in diagnostics if d["status"] in ("error", "timeout")]
    successes = [d for d in diagnostics if d["status"] in ("ok", "empty")]
    status = "partial" if errors and successes else "unavailable" if errors else "ok" if items else "empty"
    latest = {kind: next((r["published_at"] for r in items if r["kind"] == kind), None) for kind in ("news", "announcement")}
    payload = {"status": status, "code": code, "name": name or None,
               "meta": {"queried_at": now.isoformat(), "fetched_at": min((d["fetched_at"] for d in diagnostics if d.get("fetched_at")), default=now.isoformat()), "window_start": start.isoformat(), "window_end": now.isoformat(),
                        "cache_hit": False, "count": min(len(items), limit), "matched_before_limit": len(items),
                        "latest_news_at": latest["news"], "latest_announcement_at": latest["announcement"],
                        "sources": sorted(diagnostics, key=lambda d: d["source"]),
                        "coverage_limited": len(items) > limit or any(d.get("truncated") for d in diagnostics),
                        "notes": ["新闻 summary 为检索摘要，公告仅提供标题与原文链接；不自动推断事件类别或情绪。",
                                  "matched_in 仅记录精确文本出现位置，不是相关性评分；source_categories 仅保留上游原始分类。",
                                  "empty 表示已查询页在窗口内无匹配；分页受限、partial/unavailable 都不能证明公司没有事件。"]},
               "data": items[:limit]}
    if items and not errors:
        save_cache(cache_path, payload)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code", required=True)
    parser.add_argument("--name", default="", help="精确证券简称；不提供时自动查询")
    parser.add_argument("--days", type=int, default=7, help="最近 N 个自然日，含今天，默认7")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-seconds", type=float, default=20)
    parser.add_argument("--pages", type=int, default=2, help="每源最多页数，1–5")
    parser.add_argument("--scope", choices=["all", "news", "announcements"], default="all")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--include-mentions", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--title-only", action="store_true", help="可选精确标题过滤；默认保留上游查询候选，不做语义分类")
    parser.add_argument("--json", action="store_true", dest="output_json")
    args = parser.parse_args()
    if not 1 <= args.days <= 366 or not 1 <= args.limit <= 200 or not 1 <= args.pages <= 5 or not 1 <= args.max_seconds <= 60:
        parser.error("days须在1–366，limit须在1–200，pages须在1–5，max-seconds须在1–60")
    try:
        payload = build_payload(args.code, args.name, args.days, args.limit, args.max_seconds, args.pages, args.scope, args.no_cache, title_only=args.title_only)
    except ValueError as exc:
        parser.error(str(exc))
    if args.output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{payload['code']} {payload['name'] or ''} | {payload['status']} | {payload['meta']['count']} 条")
        for row in payload["data"]:
            print(f"- {row['published_at']} [{row['kind']}/{row['publisher']}/{row['matched_in']}] {row['title']}\n  {row['url']}")
        for source in payload["meta"]["sources"]:
            if source.get("error"):
                print(f"来源异常 {source['source']}: {source['error']}", file=sys.stderr)
    if payload["status"] == "unavailable":
        sys.exit(1)


if __name__ == "__main__":
    main()
