#!/usr/bin/env python3
"""
DangInvest 市场数据脚本
数据源：https://dang-invest.com

依赖：pip install requests

用法示例：
  python3 fetch_danginvest.py --news --limit 50 --json
  python3 fetch_danginvest.py --summary --mode sub --sort change_desc --limit 300 --json
  python3 fetch_danginvest.py --detail --mode concept --group-key "N:先进封装" --sort turnover_desc --json
"""

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

BASE_URL = "https://dang-invest.com/api/market"
NEWS_URL = f"{BASE_URL}/news"
BOARDS_SUMMARY_URL = f"{BASE_URL}/boards/summary"
BOARDS_DETAIL_URL = f"{BASE_URL}/boards/detail"

MODE_ALIASES = {
    "major": "industry",
    "industry": "industry",
    "大类行业": "industry",
    "sub": "ths_industry",
    "ths_industry": "ths_industry",
    "细分行业": "ths_industry",
    "concept": "ths_concept",
    "ths_concept": "ths_concept",
    "概念": "ths_concept",
}

SORT_ALIASES = {
    "market_cap_desc": "market_cap_desc",
    "market_cap": "market_cap_desc",
    "总市值": "market_cap_desc",
    "turnover_desc": "turnover_desc",
    "turnover": "turnover_desc",
    "成交额": "turnover_desc",
    "总成交额": "turnover_desc",
    "change_desc": "change_desc",
    "涨幅": "change_desc",
    "领涨": "change_desc",
    "change_asc": "change_asc",
    "跌幅": "change_asc",
    "领跌": "change_asc",
}

VALID_SORTS = frozenset(SORT_ALIASES.values())
DETAIL_INVALID_SORTS = frozenset({"changePct_desc", "changePct_asc", "change_pct_desc", "change_pct_asc"})


def _build_session(max_retries: int) -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=max_retries,
        connect=max_retries,
        read=max_retries,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _get_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    retries: int = 2,
    timeout: int = 20,
) -> Dict[str, Any]:
    session = _build_session(retries)
    last_error: Optional[Exception] = None
    attempts = retries + 1
    for attempt in range(attempts):
        try:
            resp = session.get(url, params=params or {}, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()
            if isinstance(payload, dict) and payload.get("error"):
                raise RuntimeError(str(payload.get("error")))
            return payload
        except Exception as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"请求失败（已重试 {retries} 次）：{last_error}")


def normalize_mode(mode: str) -> str:
    key = str(mode or "").strip()
    resolved = MODE_ALIASES.get(key)
    if not resolved:
        allowed = ", ".join(sorted({k for k in MODE_ALIASES if k.isascii()}))
        raise ValueError(f"未知 mode={mode!r}，可用：{allowed}")
    return resolved


def normalize_sort(sort: str, for_detail: bool = False) -> str:
    key = str(sort or "").strip()
    if for_detail and key in DETAIL_INVALID_SORTS:
        raise ValueError(
            f"detail 不支持 sort={key!r}，请使用 change_desc（涨幅）或 change_asc（跌幅）"
        )
    resolved = SORT_ALIASES.get(key, key)
    if resolved not in VALID_SORTS:
        allowed = ", ".join(sorted(VALID_SORTS))
        raise ValueError(f"未知 sort={sort!r}，可用：{allowed}")
    return resolved


def _now_meta() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cmd_news(limit: int, offset: int, retries: int, output_json: bool) -> None:
    payload = _get_json(NEWS_URL, {"limit": limit, "offset": offset}, retries=retries)
    items = payload.get("data") or []
    meta = {
        "url": NEWS_URL,
        "limit": limit,
        "offset": offset,
        "count": payload.get("count"),
        "has_more": payload.get("has_more"),
        "update_time": _now_meta(),
        "data_source": "DangInvest",
    }
    if output_json:
        print(json.dumps({"meta": meta, "data": items}, ensure_ascii=False, indent=2))
        return

    display_n = min(len(items), 20)
    print(f"【市场新闻】{meta['update_time']}  共 {len(items)} 条  数据源：DangInvest")
    for i, item in enumerate(items[:display_n]):
        item = item or {}
        published_at = item.get("published_at", "")
        source = item.get("source", "")
        title = item.get("title", "") or ""
        content = item.get("content", "") or ""
        preview = title if title else (content[:60] + ("..." if len(content) > 60 else ""))
        print(f"  {i + 1}. {published_at} [{source}] {preview}")
    if len(items) > display_n:
        print(f"  ... 已截断，共 {len(items)} 条")


def cmd_summary(mode: str, limit: int, sort: str, retries: int, output_json: bool) -> None:
    api_mode = normalize_mode(mode)
    api_sort = normalize_sort(sort, for_detail=False)
    payload = _get_json(
        BOARDS_SUMMARY_URL,
        {"mode": api_mode, "limit": limit, "sort": api_sort},
        retries=retries,
    )
    data = payload.get("data") or {}
    items = data.get("items") or []
    meta = {
        "url": BOARDS_SUMMARY_URL,
        "mode": api_mode,
        "limit": limit,
        "sort": api_sort,
        "tradeDate": payload.get("tradeDate"),
        "snapshotTsMs": payload.get("snapshotTsMs"),
        "stale": payload.get("stale"),
        "count": data.get("count"),
        "total": data.get("total"),
        "update_time": _now_meta(),
        "data_source": "DangInvest",
    }
    if output_json:
        print(json.dumps({"meta": meta, "data": items}, ensure_ascii=False, indent=2))
        return

    display_n = min(len(items), 20)
    print(
        f"【板块概览】{meta['tradeDate']}  mode={api_mode}  sort={api_sort}  "
        f"返回 {len(items)}/{meta['total']}  数据源：DangInvest"
    )
    for i, item in enumerate(items[:display_n]):
        item = item or {}
        label = item.get("groupLabel", "")
        change_pct = item.get("changePct")
        count = item.get("count", 0)
        mc_yi = round(float(item.get("totalMarketCapYuan") or 0) / 1e8, 2)
        to_yi = round(float(item.get("totalTurnoverYuan") or 0) / 1e8, 2)
        if change_pct is None:
            change_str, sign = "N/A", ""
        else:
            sign = "+" if float(change_pct) >= 0 else ""
            change_str = f"{round(float(change_pct), 2)}%"
        print(
            f"  {i + 1:>3}. {label:<14} {sign}{change_str:<8} "
            f"数量={count:<4} 市值(亿)={mc_yi} 成交(亿)={to_yi}  key={item.get('groupKey', '')}"
        )
    if len(items) > display_n:
        print(f"  ... 已截断显示前 {display_n} 个")


def cmd_detail(
    mode: str,
    group_key: str,
    sort: str,
    items_limit: int,
    items_offset: int,
    retries: int,
    output_json: bool,
) -> None:
    if not group_key:
        print("--group-key 不能为空")
        sys.exit(1)

    api_mode = normalize_mode(mode)
    api_sort = normalize_sort(sort, for_detail=True)
    payload = _get_json(
        BOARDS_DETAIL_URL,
        {
            "mode": api_mode,
            "groupKey": group_key,
            "sort": api_sort,
            "items_limit": items_limit,
            "items_offset": items_offset,
        },
        retries=retries,
    )
    meta = {
        "url": BOARDS_DETAIL_URL,
        "mode": api_mode,
        "groupKey": group_key,
        "sort": api_sort,
        "items_limit": items_limit,
        "items_offset": items_offset,
        "tradeDate": payload.get("tradeDate"),
        "snapshotTsMs": payload.get("snapshotTsMs"),
        "stale": payload.get("stale"),
        "update_time": _now_meta(),
        "data_source": "DangInvest",
    }
    data = payload.get("data") or {}
    if output_json:
        print(json.dumps({"meta": meta, "data": data}, ensure_ascii=False, indent=2))
        return

    summary = data.get("summary") or {}
    items = data.get("items") or []
    group_label = payload.get("groupLabel") or group_key
    trade_count = summary.get("count") or len(items)
    mc_yi = round(float(summary.get("totalMarketCapYuan") or 0) / 1e8, 2)
    to_yi = round(float(summary.get("totalTurnoverYuan") or 0) / 1e8, 2)
    change_pct = summary.get("changePct")
    if change_pct is None:
        change_str, sign = "N/A", ""
    else:
        sign = "+" if float(change_pct) >= 0 else ""
        change_str = f"{round(float(change_pct), 2)}%"
    print(
        f"【板块成分】{meta['tradeDate']}  {group_label}  mode={api_mode}  sort={api_sort}  "
        f"数量={trade_count} 市值(亿)={mc_yi} 成交(亿)={to_yi} 涨跌幅={sign}{change_str}"
    )

    display_n = min(len(items), 20)
    for i, item in enumerate(items[:display_n]):
        item = item or {}
        code = item.get("code", "")
        name = item.get("name", "")
        price = item.get("price")
        cp = item.get("changePct")
        to_yi_i = round(float(item.get("turnoverYuan") or 0) / 1e8, 2)
        mc_yi_i = round(float(item.get("marketCapYuan") or 0) / 1e8, 2)
        price_str = str(round(float(price), 2)) if price is not None else "N/A"
        if cp is None:
            cp_str, sign_i = "N/A", ""
        else:
            sign_i = "+" if float(cp) >= 0 else ""
            cp_str = f"{round(float(cp), 2)}%"
        print(
            f"  {i + 1:>3}. {code:<12} {name:<12} 现价={price_str:<8} "
            f"{sign_i}{cp_str:<8} 成交(亿)={to_yi_i} 市值(亿)={mc_yi_i}"
        )
    if len(items) > display_n:
        items_meta = data.get("itemsMeta") or {}
        total = items_meta.get("total", len(items))
        print(f"  ... 已截断显示前 {display_n} 只（本页 {len(items)} 只，总计 {total} 只）")


def main() -> None:
    parser = argparse.ArgumentParser(description="DangInvest 市场数据（板块热力图 + 新闻）")
    parser.add_argument("--news", action="store_true", help="7x24 市场新闻")
    parser.add_argument("--summary", action="store_true", help="板块热力图概览")
    parser.add_argument("--detail", action="store_true", help="板块成分明细")
    parser.add_argument("--limit", type=int, default=300, help="summary/news 条数（默认 300）")
    parser.add_argument("--offset", type=int, default=0, help="news 偏移（默认 0）")
    parser.add_argument(
        "--mode",
        default="sub",
        help="板块维度：major/sub/concept（或 ths_industry/industry/ths_concept）",
    )
    parser.add_argument(
        "--sort",
        default="change_desc",
        help="排序：change_desc|turnover_desc|market_cap_desc|change_asc（默认 change_desc 涨幅）",
    )
    parser.add_argument("--group-key", default="", help="detail 必填，summary 返回的 groupKey")
    parser.add_argument("--items-limit", type=int, default=300, help="detail 成分条数（默认 300）")
    parser.add_argument("--items-offset", type=int, default=0, help="detail 成分偏移（默认 0）")
    parser.add_argument("--retries", type=int, default=2, help="失败重试次数（默认 2）")
    parser.add_argument("--json", dest="output_json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    selected = sum(bool(x) for x in (args.news, args.summary, args.detail))
    if selected != 1:
        parser.error("请指定且仅指定一个子命令：--news / --summary / --detail")

    try:
        if args.news:
            cmd_news(args.limit, args.offset, args.retries, args.output_json)
        elif args.summary:
            cmd_summary(args.mode, args.limit, args.sort, args.retries, args.output_json)
        else:
            cmd_detail(
                args.mode,
                args.group_key,
                args.sort,
                args.items_limit,
                args.items_offset,
                args.retries,
                args.output_json,
            )
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
