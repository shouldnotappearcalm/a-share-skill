#!/usr/bin/env python3
"""
A股赴港上市关键事件时间节点查询

参考实现要点：
- 港股名 -> A股代码 自动解析（缓存映射）
- 东方财富公告分段/分页抓取
- 先做 H 股相关公告过滤，再做里程碑正则匹配
- 时间窗口默认：H 股上市日前 3 年 ~ 上市后 180 天
- 支持批量与单票查询
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


# ------------------------------
# 通用
# ------------------------------

class _CallTimeout(Exception):
    pass


def _safe_ak_call(fn, *args, timeout_sec: int = 12, **kwargs):
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


def _parse_date(s: Any) -> Optional[datetime]:
    if s is None:
        return None
    x = str(s).strip()
    if not x:
        return None
    x = x.replace("/", "-")
    if " " in x:
        x = x.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(x, fmt)
        except ValueError:
            pass
    return None


def _normalize_hk_code(raw: str) -> str:
    s = str(raw).strip().upper()
    if s.endswith(".HK"):
        s = s[:-3]
    return s.zfill(5) if s.isdigit() else s


# ------------------------------
# 路径/缓存
# ------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = SCRIPT_DIR.parent / "cache"
AH_CACHE_FILE = CACHE_DIR / "ah_stocks.json"
TIMELINE_CACHE_FILE = CACHE_DIR / "ah_ipo_timeline.json"
CODE_MAPPING_FILE = CACHE_DIR / "ah_code_mapping.json"

TIMELINE_TTL = 24 * 3600
CODE_MAPPING_TTL = 30 * 24 * 3600

_CODE_MAPPING_LOCK = threading.Lock()
_CODE_MAPPING_DIRTY = False


def _load_json_if_fresh(path: Path, ttl: int) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        ts = float(obj.get("generated_at", 0))
        if time.time() - ts > ttl:
            return None
        return obj
    except Exception:
        return None


def _save_json(path: Path, payload: Dict[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_code_mapping() -> Dict[str, str]:
    obj = _load_json_if_fresh(CODE_MAPPING_FILE, CODE_MAPPING_TTL)
    if not obj:
        return {}
    data = obj.get("data", {})
    return data if isinstance(data, dict) else {}


def _save_code_mapping(mapping: Dict[str, str]):
    _save_json(CODE_MAPPING_FILE, {
        "generated_at": time.time(),
        "generated_at_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(mapping),
        "data": mapping,
    })


# ------------------------------
# A/H 列表
# ------------------------------

def _load_ah_from_cache() -> List[Dict[str, Any]]:
    if not AH_CACHE_FILE.exists():
        return []
    try:
        obj = json.loads(AH_CACHE_FILE.read_text(encoding="utf-8"))
        rows = obj.get("data", [])
        return rows if isinstance(rows, list) else []
    except Exception:
        return []


def _fetch_ah_spot_list() -> List[Dict[str, Any]]:
    df = _safe_ak_call(ak.stock_zh_ah_spot_em, timeout_sec=20)
    if df is None or df.empty:
        return []

    out = []
    for _, row in df.iterrows():
        out.append({
            "ah_name": str(row.get("名称", "")).strip(),
            "a_code": str(row.get("A股代码", "")).strip(),
            "hk_code": _normalize_hk_code(row.get("H股代码", "")),
            "list_date": None,
        })
    return out


def _query_hk_profile(hk_code: str) -> Dict[str, Any]:
    try:
        df = _safe_ak_call(ak.stock_hk_security_profile_em, symbol=hk_code, timeout_sec=10)
        if df is None or df.empty:
            return {"hk_code": hk_code, "profile_error": "empty"}
        row = {k: _to_native(v) for k, v in df.iloc[0].to_dict().items()}
        return {
            "hk_code": hk_code,
            "security_name": row.get("证券简称"),
            "list_date": str(row.get("上市日期", "")).split(" ")[0] if row.get("上市日期") else None,
            "security_type": row.get("证券类型"),
            "board": row.get("板块"),
            "is_sh_connect": row.get("是否沪港通标的"),
            "is_sz_connect": row.get("是否深港通标的"),
            "profile_error": None,
        }
    except Exception as e:
        return {"hk_code": hk_code, "profile_error": str(e)}


def _fetch_ah_stocks(max_workers: int = 8, use_cache: bool = True) -> List[Dict[str, Any]]:
    if use_cache:
        cached = _load_ah_from_cache()
        if cached:
            return cached

    items = _fetch_ah_spot_list()
    if not items:
        return []

    prof_map: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        futs = {ex.submit(_query_hk_profile, s["hk_code"]): s["hk_code"] for s in items}
        for fut in as_completed(futs):
            hk = futs[fut]
            try:
                prof_map[hk] = fut.result()
            except Exception as e:
                prof_map[hk] = {"hk_code": hk, "profile_error": str(e)}

    out = []
    for s in items:
        p = prof_map.get(s["hk_code"], {})
        out.append({
            "ah_name": s.get("ah_name"),
            "a_code": s.get("a_code"),
            "hk_code": s.get("hk_code"),
            "security_name": p.get("security_name") or s.get("ah_name"),
            "list_date": p.get("list_date"),
            "security_type": p.get("security_type"),
            "board": p.get("board"),
            "is_sh_connect": p.get("is_sh_connect"),
            "is_sz_connect": p.get("is_sz_connect"),
            "profile_error": p.get("profile_error"),
        })

    _save_json(AH_CACHE_FILE, {
        "generated_at": time.time(),
        "generated_at_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(out),
        "data": out,
    })
    return out


# ------------------------------
# 港股名 -> A股代码 自动解析
# ------------------------------

def _search_a_code(keyword: str) -> Optional[str]:
    # 东方财富 suggest 接口
    try:
        resp = requests.get(
            "https://searchapi.eastmoney.com/api/suggest/get",
            params={"input": keyword, "type": "14", "count": "8"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=6,
        )
        arr = resp.json().get("QuotationCodeTable", {}).get("Data", []) or []
        for item in arr:
            classify = str(item.get("Classify", ""))
            code = str(item.get("Code", "")).strip()
            # 23: A股（常见）
            if classify == "23" and code.isdigit() and len(code) == 6:
                return code
    except Exception:
        return None
    return None


def _resolve_a_code(name: str, hint_a_code: str = "", code_mapping: Optional[Dict[str, str]] = None) -> Optional[str]:
    if hint_a_code and hint_a_code.isdigit() and len(hint_a_code) == 6:
        return hint_a_code

    clean = str(name or "").strip().replace("*", "")
    if not clean:
        return None

    mapping = code_mapping if code_mapping is not None else _load_code_mapping()
    if clean in mapping:
        return mapping[clean]

    candidates = [clean]
    for suffix in ["股份", "科技", "集团", "控股", "有限公司", "国际"]:
        if clean.endswith(suffix) and len(clean) > len(suffix):
            candidates.append(clean[:-len(suffix)])

    # 一个常见英文名兜底示例
    if clean.upper() == "FORTIOR":
        candidates.append("峰岹科技")

    found = None
    for kw in candidates:
        code = _search_a_code(kw)
        if code:
            found = code
            break

    if found:
        with _CODE_MAPPING_LOCK:
            mapping[clean] = found
            _save_code_mapping(mapping)
        return found

    return None


# ------------------------------
# 公告抓取 + 节点提取
# ------------------------------

_MILESTONE_PATTERNS = [
    (r"递表|递交.*申请|刊发申请资料|更新申请资料", "submit"),
    (r"聆讯|通过.*聆讯|聆讯后资料集|联交所审议|PHIP", "hearing"),
    (r"境外发行上市备案|备案通知书|证监会.*备案", "filing"),
    (r"招股书|招股章程|全球发售|公开发售|国际配售", "prospectus"),
    (r"定价|发售价|发行价", "pricing"),
    (r"配售结果|分配结果|中签结果", "allotment"),
    (r"挂牌上市|H股上市|上市交易", "listing"),
]

_H_FILTER = r"H股|境外上市|港交所|香港联交所|香港交易所|发行境外上市外资股|全球发售|招股"


def _fetch_announcements(a_code: str, begin: str, end: str, max_pages: int = 30) -> List[Dict[str, Any]]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://data.eastmoney.com/",
    }
    all_items: List[Dict[str, Any]] = []

    for page in range(1, max_pages + 1):
        params = {
            "sr": -1,
            "page_size": "100",
            "page_index": str(page),
            "ann_type": "SHA,SZA",
            "client_source": "web",
            "f_node": "0",
            "s_node": "0",
            "begin_time": begin,
            "end_time": end,
            "stock_list": a_code,
        }
        try:
            resp = requests.get(
                "https://np-anotice-stock.eastmoney.com/api/security/ann",
                params=params,
                headers=headers,
                timeout=8,
            )
            items = resp.json().get("data", {}).get("list", []) or []
            if not items:
                break
            all_items.extend(items)
            if len(items) < 100:
                break
        except Exception:
            break
    return all_items


def _extract_milestones(announcements: List[Dict[str, Any]], listing_date: Optional[str]) -> Dict[str, Any]:
    cutoff = None
    if listing_date:
        dt = _parse_date(listing_date)
        if dt:
            cutoff = (dt - timedelta(days=365 * 3)).strftime("%Y-%m-%d")

    hk_anns = []
    for ann in announcements:
        title = str(ann.get("title", ""))
        notice_date = str(ann.get("notice_date", ""))[:10]
        if not title or not notice_date:
            continue
        if not re.search(_H_FILTER, title):
            continue
        if cutoff and notice_date < cutoff:
            continue
        hk_anns.append({"date": notice_date, "title": title})

    hk_anns.sort(key=lambda x: x["date"])

    milestones: Dict[str, Dict[str, str]] = {}
    for patt, name in _MILESTONE_PATTERNS:
        for ann in hk_anns:
            if re.search(patt, ann["title"]):
                milestones[name] = {"date": ann["date"], "title": ann["title"]}
                break

    return {
        "milestones": milestones,
        "events": hk_anns,
        "event_count": len(hk_anns),
    }


def _query_milestones_for_stock(stock: Dict[str, Any], code_mapping: Dict[str, str]) -> Dict[str, Any]:
    name = stock.get("ah_name") or stock.get("security_name") or ""
    hk_code = stock.get("hk_code") or ""
    listing_date = stock.get("list_date")

    a_code = _resolve_a_code(name, hint_a_code=stock.get("a_code", ""), code_mapping=code_mapping)
    if not a_code:
        return {
            "name": name,
            "a_code": None,
            "hk_code": hk_code,
            "list_date": listing_date,
            "error": "无法解析A股代码",
            "milestones": {},
            "events": [],
            "event_count": 0,
        }

    # 查询时间窗：优先围绕上市日；若无上市日，用近6年
    if listing_date and _parse_date(listing_date):
        dt = _parse_date(listing_date)
        begin = (dt - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
        end = (dt + timedelta(days=180)).strftime("%Y-%m-%d")
    else:
        begin = (datetime.now() - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
        end = datetime.now().strftime("%Y-%m-%d")

    anns = _fetch_announcements(a_code, begin, end)
    extracted = _extract_milestones(anns, listing_date)

    return {
        "name": name,
        "a_code": a_code,
        "hk_code": hk_code,
        "list_date": listing_date,
        "error": None,
        "milestones": extracted["milestones"],
        "events": extracted["events"],
        "event_count": extracted["event_count"],
        "query_window": {"begin": begin, "end": end},
    }


def _batch_query_milestones(stocks: List[Dict[str, Any]], max_workers: int = 4, use_cache: bool = True) -> Dict[str, Dict]:
    # target 场景不走批量缓存，避免旧数据干扰
    if use_cache:
        cached = _load_json_if_fresh(TIMELINE_CACHE_FILE, TIMELINE_TTL)
        if cached and isinstance(cached.get("data"), dict):
            return cached["data"]

    code_mapping = _load_code_mapping()
    results: Dict[str, Dict] = {}

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
        futs = {ex.submit(_query_milestones_for_stock, s, code_mapping): s for s in stocks}
        for fut in as_completed(futs):
            s = futs[fut]
            key = s.get("hk_code") or s.get("a_code") or s.get("ah_name")
            try:
                results[key] = fut.result()
            except Exception as e:
                results[key] = {
                    "name": s.get("ah_name"),
                    "a_code": s.get("a_code"),
                    "hk_code": s.get("hk_code"),
                    "list_date": s.get("list_date"),
                    "error": str(e),
                    "milestones": {},
                    "events": [],
                    "event_count": 0,
                }

    if use_cache:
        _save_json(TIMELINE_CACHE_FILE, {
            "generated_at": time.time(),
            "generated_at_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(results),
            "data": results,
        })
    return results


def _match_target(stock: Dict[str, Any], code: str = "", name: str = "") -> bool:
    c = (code or "").strip().upper()
    n = (name or "").strip().lower()

    a = str(stock.get("a_code") or "").upper()
    h = str(stock.get("hk_code") or "").upper()
    nm = str(stock.get("ah_name") or stock.get("security_name") or "").lower()

    if c and c not in {a, h, h.zfill(5)}:
        return False
    if n and n not in nm:
        return False
    return True


def _format_row(info: Dict[str, Any]) -> Dict[str, Any]:
    m = info.get("milestones", {}) or {}
    return {
        "name": info.get("name"),
        "a_code": info.get("a_code"),
        "hk_code": info.get("hk_code"),
        "list_date": info.get("list_date"),
        "submit_date": (m.get("submit") or {}).get("date"),
        "hearing_date": (m.get("hearing") or {}).get("date"),
        "filing_date": (m.get("filing") or {}).get("date"),
        "prospectus_date": (m.get("prospectus") or {}).get("date"),
        "pricing_date": (m.get("pricing") or {}).get("date"),
        "allotment_date": (m.get("allotment") or {}).get("date"),
        "listing_announce_date": (m.get("listing") or {}).get("date"),
        "event_count": info.get("event_count", 0),
        "error": info.get("error"),
        "events": info.get("events", []),
    }


def main():
    parser = argparse.ArgumentParser(description="查询A股赴港上市关键事件时间节点")
    parser.add_argument("--since", type=int, default=2020, help="全量模式起始年份")
    parser.add_argument("--workers", type=int, default=4, help="并发数")
    parser.add_argument("--no-cache", action="store_true", help="全量模式禁用缓存")
    parser.add_argument("--code", default="", help="A股或H股代码，如 601127 / 09927")
    parser.add_argument("--name", default="", help="股票名称，如 赛力斯")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON")
    parser.add_argument("--limit", type=int, default=50, help="文本输出条数")
    args = parser.parse_args()

    ah_stocks = _fetch_ah_stocks(max_workers=max(1, args.workers), use_cache=True)
    if not ah_stocks:
        print(json.dumps({"error": "无法获取A/H股票列表", "data": []}, ensure_ascii=False))
        return

    target_mode = bool(args.code or args.name)

    if target_mode:
        pool = [s for s in ah_stocks if _match_target(s, code=args.code, name=args.name)]
        results = _batch_query_milestones(pool, max_workers=max(1, args.workers), use_cache=False)
        rows = [_format_row(v) for v in results.values()]
    else:
        pool = []
        for s in ah_stocks:
            dt = _parse_date(s.get("list_date"))
            if dt and dt.year >= args.since:
                pool.append(s)
        results = _batch_query_milestones(pool, max_workers=max(1, args.workers), use_cache=(not args.no_cache))
        rows = [_format_row(v) for v in results.values()]

    rows.sort(key=lambda x: (x.get("list_date") or "9999-99-99", x.get("hk_code") or ""), reverse=True)

    output = {
        "query": {
            "since": args.since,
            "workers": args.workers,
            "no_cache": bool(args.no_cache),
            "code": args.code or None,
            "name": args.name or None,
            "target_mode": target_mode,
        },
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total": len(rows),
            "target_candidates": len(pool),
        },
        "data": rows,
    }

    if args.output_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    show = rows[:max(1, args.limit)]
    print(f"查询完成：共 {len(rows)} 条（展示 {len(show)} 条）")
    print("-" * 150)
    print(f"{'A股':<8} {'H股':<8} {'名称':<10} {'递表':<12} {'聆讯':<12} {'备案':<12} {'招股':<12} {'上市':<12} {'事件数':<6}")
    print("-" * 150)
    for r in show:
        print(
            f"{str(r.get('a_code') or '-'):8} "
            f"{str(r.get('hk_code') or '-'):8} "
            f"{str(r.get('name') or '-')[:8]:10} "
            f"{str(r.get('submit_date') or '-'):12} "
            f"{str(r.get('hearing_date') or '-'):12} "
            f"{str(r.get('filing_date') or '-'):12} "
            f"{str(r.get('prospectus_date') or '-'):12} "
            f"{str(r.get('list_date') or r.get('listing_announce_date') or '-'):12} "
            f"{str(r.get('event_count') or 0):6}"
        )


if __name__ == "__main__":
    main()
