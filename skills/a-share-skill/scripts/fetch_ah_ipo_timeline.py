#!/usr/bin/env python3
"""
A股赴港上市(IPO)关键时间节点查询

能力：
1) 查询 A->H 关键节点：递表、聆讯、招股、定价、配售结果、上市、超额配售等
2) 支持按股票代码/名称精准查询（即使 list_date 缺失也可强制查询）
3) 支持全量缓存结果输出
"""

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import akshare as ak
import numpy as np
import pandas as pd
import requests


class _CallTimeout(Exception):
    pass


def _safe_ak_call(fn, *args, timeout_sec: int = 15, **kwargs):
    result = {"value": None, "error": None}

    def _runner():
        try:
            result["value"] = fn(*args, **kwargs)
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=max(1, int(timeout_sec)))
    if t.is_alive():
        raise _CallTimeout(f"timeout>{timeout_sec}s")
    if result["error"] is not None:
        raise result["error"]
    return result["value"]


def _to_native(v: Any):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if pd.isna(v):
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.strftime("%Y-%m-%d")
    return v


def _parse_date(date_str: Any) -> Optional[datetime]:
    if date_str is None:
        return None
    s = str(date_str).strip()
    if not s:
        return None
    s = s.replace("/", "-")
    if " " in s:
        s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _normalize_hk_code(raw: str) -> str:
    s = str(raw).strip().upper()
    if s.endswith(".HK"):
        s = s[:-3]
    if s.isdigit():
        return s.zfill(5)
    return s


def _load_cache(cache_file: Path, ttl_sec: int) -> Optional[Dict[str, Any]]:
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        ts = float(payload.get("generated_at", 0))
        if time.time() - ts > ttl_sec:
            return None
        return payload
    except Exception:
        return None


def _save_cache(cache_file: Path, data: Dict[str, Any]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_ah_stocks_cache() -> List[Dict[str, Any]]:
    script_dir = Path(__file__).resolve().parent
    cache_file = script_dir.parent / "cache" / "ah_stocks.json"
    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            return payload.get("data", []) or []
        except Exception:
            return []
    return []


def _fetch_ah_stock_list() -> List[Dict[str, Any]]:
    try:
        df = _safe_ak_call(ak.stock_zh_ah_spot_em, timeout_sec=30)
        if df is None or df.empty:
            return []
        items = []
        for _, row in df.iterrows():
            items.append({
                "hk_code": _normalize_hk_code(row.get("H股代码", "")),
                "a_code": str(row.get("A股代码", "")).strip(),
                "ah_name": str(row.get("名称", "")).strip(),
                "list_date": None,
            })
        return items
    except Exception:
        return []


def _search_ipo_announcements(
    a_code: str,
    start_date: str,
    end_date: str,
    page_size: int = 100,
    max_pages: int = 4,
) -> List[Dict[str, Any]]:
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"

    ipo_patterns = [
        r"递表|递交.*申请|刊发申请资料|更新申请资料",
        r"聆讯|通过.*聆讯|聆讯后资料集|PHIP|联交所审议",
        r"境外发行上市备案|备案通知书|证监会.*备案",
        r"招股书|招股章程|全球发售|公开发售|国际配售",
        r"定价|发售价|发行价",
        r"配售结果|分配结果|中签|超额配股权|稳定价格期",
        r"挂牌上市|H股上市|上市交易|在港上市",
        r"港交所|香港联交所|香港交易所|发行H股",
    ]

    all_announcements: List[Dict[str, Any]] = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    seg_start = start_dt
    while seg_start <= end_dt:
        seg_end = min(seg_start + timedelta(days=180), end_dt)
        for page in range(1, max_pages + 1):
            params = {
                "sr": -1,
                "page_size": page_size,
                "page_index": page,
                "ann_type": "SHA,SZA",
                "client_source": "web",
                "f_node": 0,
                "s_node": 0,
                "begin_time": seg_start.strftime("%Y-%m-%d"),
                "end_time": seg_end.strftime("%Y-%m-%d"),
                "stock_list": a_code,
            }

            ok = False
            for _ in range(1):
                try:
                    resp = requests.get(
                        url,
                        params=params,
                        timeout=6,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                        },
                    )
                    data = resp.json()
                    items = data.get("data", {}).get("list", []) or []
                    ok = True
                    if not items:
                        break

                    for item in items:
                        title = str(item.get("title", ""))
                        if not title:
                            continue
                        if not any(re.search(p, title) for p in ipo_patterns):
                            continue
                        art_code = item.get("art_code", "")
                        if art_code and any(x.get("art_code") == art_code for x in all_announcements):
                            continue
                        all_announcements.append(
                            {
                                "art_code": art_code,
                                "title": title,
                                "notice_date": str(item.get("notice_date", ""))[:10],
                            }
                        )
                    if len(items) < page_size:
                        break
                    break
                except Exception:
                    continue
            if not ok:
                break

        seg_start = seg_end + timedelta(days=1)

    return sorted(all_announcements, key=lambda x: x.get("notice_date", ""))


def _extract_timeline_from_announcements(announcements: List[Dict[str, Any]]) -> Dict[str, Any]:
    def _pick_first(pattern: str) -> Optional[str]:
        for ann in announcements:
            if re.search(pattern, ann.get("title", "")):
                return ann.get("notice_date")
        return None

    timeline = {
        "submit_date": _pick_first(r"递表|递交.*申请|刊发申请资料|更新申请资料"),
        "hearing_date": _pick_first(r"聆讯|通过.*聆讯|聆讯后资料集|PHIP|联交所审议"),
        "filing_date": _pick_first(r"境外发行上市备案|备案通知书|证监会.*备案"),
        "prospectus_date": _pick_first(r"招股书|招股章程|全球发售|公开发售|国际配售"),
        "pricing_date": _pick_first(r"定价|发售价|发行价"),
        "allotment_result_date": _pick_first(r"配售结果|分配结果|中签"),
        "greenshoe_date": _pick_first(r"超额配股权|稳定价格期"),
        "list_announce_date": _pick_first(r"挂牌上市|H股上市|上市交易|在港上市"),
        "events": [],
    }

    event_patterns = [
        ("submit", r"递表|递交.*申请|刊发申请资料|更新申请资料"),
        ("hearing", r"聆讯|通过.*聆讯|聆讯后资料集|PHIP|联交所审议"),
        ("filing", r"境外发行上市备案|备案通知书|证监会.*备案"),
        ("prospectus", r"招股书|招股章程|全球发售|公开发售|国际配售"),
        ("pricing", r"定价|发售价|发行价"),
        ("allotment", r"配售结果|分配结果|中签"),
        ("greenshoe", r"超额配股权|稳定价格期"),
        ("listing", r"挂牌上市|H股上市|上市交易|在港上市"),
    ]

    seen = set()
    for ann in announcements:
        title = ann.get("title", "")
        d = ann.get("notice_date")
        if not d:
            continue
        for ev_type, patt in event_patterns:
            if re.search(patt, title):
                key = (ev_type, d, title)
                if key in seen:
                    continue
                seen.add(key)
                timeline["events"].append(
                    {"date": d, "type": ev_type, "title": title, "source": "eastmoney_announcement"}
                )
                break

    timeline["events"] = sorted(timeline["events"], key=lambda x: x["date"])
    return timeline


def _matches_target(stock: Dict[str, Any], code: str = "", name: str = "") -> bool:
    code = (code or "").strip().upper()
    name = (name or "").strip().lower()

    a_code = str(stock.get("a_code") or "").upper()
    hk_code = str(stock.get("hk_code") or "").upper()
    ah_name = str(stock.get("ah_name") or stock.get("name") or stock.get("security_name") or "")
    ah_name_l = ah_name.lower()

    if code:
        code_ok = code in {a_code, hk_code, hk_code.zfill(5)}
        if not code_ok:
            return False
    if name and name not in ah_name_l:
        return False
    return True


def _build_rows_for_stocks(stocks: List[Dict[str, Any]], since_year: int = 2020, workers: int = 3) -> List[Dict[str, Any]]:
    end_date = datetime.now().strftime("%Y-%m-%d")

    def _process(stock: Dict[str, Any]) -> Dict[str, Any]:
        a_code = str(stock.get("a_code") or "")
        list_date = str(stock.get("list_date") or "")

        # 即使 list_date 缺失，也强制查公告（解决用户点查时漏数据问题）
        start_date = f"{since_year}-01-01"
        if list_date:
            dt = _parse_date(list_date)
            if dt:
                start_date = (dt - timedelta(days=900)).strftime("%Y-%m-%d")

        anns = _search_ipo_announcements(a_code, start_date, end_date)
        timeline = _extract_timeline_from_announcements(anns)

        return {
            "a_code": a_code,
            "hk_code": str(stock.get("hk_code") or ""),
            "name": str(stock.get("ah_name") or stock.get("name") or stock.get("security_name") or ""),
            "submit_date": timeline.get("submit_date"),
            "hearing_date": timeline.get("hearing_date"),
            "filing_date": timeline.get("filing_date"),
            "prospectus_date": timeline.get("prospectus_date"),
            "pricing_date": timeline.get("pricing_date"),
            "allotment_result_date": timeline.get("allotment_result_date"),
            "greenshoe_date": timeline.get("greenshoe_date"),
            "list_date": list_date or None,
            "list_announce_date": timeline.get("list_announce_date"),
            "announce_count": len(anns),
            "events": timeline.get("events", []),
        }

    rows: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(_process, s) for s in stocks if s.get("a_code")]
        for fut in as_completed(futs):
            try:
                rows.append(fut.result())
            except Exception:
                pass

    rows.sort(key=lambda x: (x.get("list_date") or "9999-99-99", x.get("a_code") or ""), reverse=True)
    return rows


def _print_table(rows: List[Dict[str, Any]], limit: int = 50) -> None:
    show = rows[:limit]
    if not show:
        print("无结果")
        return

    print(f"A股赴港上市关键节点：{len(rows)} 条（展示前 {len(show)} 条）")
    print("-" * 150)
    print(f"{'A股':<8} {'H股':<8} {'名称':<12} {'递表':<12} {'聆讯':<12} {'备案':<12} {'招股':<12} {'上市':<12} {'事件数':<6}")
    print("-" * 150)
    for r in show:
        print(
            f"{str(r.get('a_code') or ''):<8} "
            f"{str(r.get('hk_code') or ''):<8} "
            f"{str(r.get('name') or '')[:10]:<12} "
            f"{str(r.get('submit_date') or '-'):<12} "
            f"{str(r.get('hearing_date') or '-'):<12} "
            f"{str(r.get('filing_date') or '-'):<12} "
            f"{str(r.get('prospectus_date') or '-'):<12} "
            f"{str(r.get('list_date') or r.get('list_announce_date') or '-'):<12} "
            f"{str(r.get('announce_count') or 0):<6}"
        )


def main():
    parser = argparse.ArgumentParser(description="查询A股赴港上市关键时间节点")
    parser.add_argument("--since", type=int, default=2020, help="起始年份，默认2020")
    parser.add_argument("--workers", type=int, default=3, help="并发数，默认3")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存，强制刷新")
    parser.add_argument("--code", default="", help="按A股/港股代码过滤，如 601127 / 09927")
    parser.add_argument("--name", default="", help="按名称过滤，如 赛力斯")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出JSON")
    parser.add_argument("--limit", type=int, default=50, help="文本模式最多展示条数")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    cache_file = script_dir.parent / "cache" / "ah_ipo_timeline.json"
    ttl_sec = 24 * 3600

    # 准备股票池（优先 ah_stocks 缓存，缺失则实时拉取）
    ah_rows = _load_ah_stocks_cache()
    if not ah_rows:
        ah_rows = _fetch_ah_stock_list()

    if args.code or args.name:
        target_stocks = [s for s in ah_rows if _matches_target(s, code=args.code, name=args.name)]
        rows = _build_rows_for_stocks(target_stocks, since_year=args.since, workers=args.workers)
        meta = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "since_year": args.since,
            "total": len(rows),
            "cache_hit": False,
            "cache_file": str(cache_file),
            "filtered": len(rows),
            "target_mode": True,
            "target_input": {"code": args.code or None, "name": args.name or None},
            "target_stock_candidates": len(target_stocks),
        }
    else:
        cache_hit = False
        cached_data = None
        if not args.no_cache:
            cached_data = _load_cache(cache_file, ttl_sec)
            cache_hit = cached_data is not None

        if cached_data:
            rows = cached_data.get("data", [])
            old_meta = cached_data.get("meta", {})
            meta = {
                **old_meta,
                "cache_hit": cache_hit,
                "cache_file": str(cache_file),
                "filtered": len(rows),
                "target_mode": False,
            }
        else:
            stocks = []
            for s in ah_rows:
                d = _parse_date(s.get("list_date"))
                if d and d.year >= args.since:
                    stocks.append(s)
            rows = _build_rows_for_stocks(stocks, since_year=args.since, workers=args.workers)
            meta = {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "since_year": args.since,
                "total": len(rows),
                "cache_hit": False,
                "cache_file": str(cache_file),
                "filtered": len(rows),
                "target_mode": False,
            }
            _save_cache(cache_file, {"generated_at": time.time(), "meta": meta, "data": rows})

    output = {
        "query": {
            "since_year": args.since,
            "workers": args.workers,
            "no_cache": bool(args.no_cache),
            "code": args.code or None,
            "name": args.name or None,
        },
        "meta": meta,
        "data": rows,
    }

    if args.output_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    print(
        f"查询完成：总计 {output['meta'].get('total', 0)} 条，"
        f"筛选后 {output['meta'].get('filtered', 0)} 条，"
        f"target_mode={output['meta'].get('target_mode')}"
    )
    _print_table(rows, limit=max(1, args.limit))


if __name__ == "__main__":
    main()
