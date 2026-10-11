"""HTTP and pagination primitives for provider-native reference data."""
from datetime import datetime
import re
import threading
import time
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Asia/Shanghai")
_HTTP = threading.local()


class UpstreamError(ValueError):
    pass


def now_iso():
    return datetime.now(TZ).isoformat()


def stock_identity(code):
    value = str(code or "").strip().upper()
    match = re.fullmatch(r"(?:(SH|SZ|BJ)\.?)(\d{6})", value)
    if match:
        market, digits = match.groups()
    else:
        match = re.fullmatch(r"(\d{6})(?:\.(SH|SZ|BJ|XSHG|XSHE))?", value)
        if not match:
            raise ValueError("code must identify a six-digit A-share stock")
        digits, market = match.groups()
        market = {"XSHG": "SH", "XSHE": "SZ"}.get(market, market)
    inferred = "SH" if digits.startswith("6") else "BJ" if digits.startswith(("4", "8", "92")) else "SZ"
    if market and market != inferred:
        raise ValueError("stock prefix conflicts with the supported A-share code convention")
    return {"code": digits, "market": market or inferred, "secu_code": f"{digits}.{market or inferred}"}


def iso_date(value):
    if not value:
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return datetime.strptime(text, "%Y-%m-%d").date().isoformat()


def session():
    if not hasattr(_HTTP, "session"):
        client = requests.Session()
        client.trust_env = False
        client.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json,text/html,*/*"})
        _HTTP.session = client
    return _HTTP.session


def request(url, deadline, params=None, referer=None):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("overall source deadline exceeded")
    response = session().get(url, params=params, headers={"Referer": referer} if referer else {}, timeout=min(6, remaining))
    response.raise_for_status()
    return response


def get_json(url, deadline, **kwargs):
    value = request(url, deadline, **kwargs).json()
    if not isinstance(value, dict):
        raise UpstreamError("expected a JSON object")
    return value


def datacenter(report, filter_, sort, deadline, max_pages=10, page_size=100):
    """Retain rows verbatim; reject API errors and expose incomplete pagination."""
    rows, errors, total, pages, fetched = [], [], None, None, 0
    for page in range(1, max_pages + 1):
        params = {"reportName": report, "columns": "ALL", "filter": filter_,
                  "sortColumns": sort, "sortTypes": ",".join(["-1"] * len(sort.split(","))),
                  "pageSize": page_size, "pageNumber": page, "source": "WEB", "client": "WEB"}
        try:
            obj = get_json("https://datacenter-web.eastmoney.com/api/data/v1/get", deadline,
                           params=params, referer="https://data.eastmoney.com/")
            if obj.get("success") is not True:
                raise UpstreamError(f"API {obj.get('code')}: {obj.get('message')}")
            result = obj.get("result")
            if result is None:
                if page == 1:
                    total, pages = 0, 0
                    break
                raise UpstreamError("pagination unexpectedly returned no result")
            batch = result.get("data")
            if not isinstance(batch, list):
                raise UpstreamError("datacenter row schema changed")
            total, pages = int(result["count"]), int(result["pages"])
            rows.extend(batch)
            fetched += 1
            if page >= pages or len(rows) >= total:
                break
            if not batch:
                raise UpstreamError("empty page before advertised end")
        except Exception as exc:
            if not rows:
                raise
            errors.append(f"{type(exc).__name__}: {exc}")
            break
    limited = total is None or len(rows) < total or bool(errors)
    return rows, {"total": total, "upstream_pages": pages, "pages_fetched": fetched,
                  "coverage_limited": limited, "errors": errors, "report_name": report}


def failed(exc, **metadata):
    return {"status": "unavailable", "error": f"{type(exc).__name__}: {exc}",
            "meta": dict(metadata, fetched_at=now_iso()), "data": []}
