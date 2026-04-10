#!/usr/bin/env python3
"""
A/H 双重上市公司列表查询

能力：
1) 获取全量 A+H 上市公司列表（ak.stock_zh_ah_name）
2) 并发补充每只 H 股的基本资料（ak.stock_hk_security_profile_em）
3) 支持按 H 股上市日期区间筛选
4) 本地缓存（默认 12 小时 TTL）

依赖：pip install akshare pandas numpy
"""

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import akshare as ak
import numpy as np
import pandas as pd


class _CallTimeout(Exception):
    pass


def _safe_ak_call(fn, *args, timeout_sec: int = 10, **kwargs):
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


def _clean_record(rec: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _to_native(v) for k, v in rec.items()}


def _parse_date(date_str: Any) -> Optional[datetime]:
    if date_str is None:
        return None
    s = str(date_str).strip()
    if not s:
        return None
    s = s.replace("/", "-")
    if " " in s:
        s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
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


def _fetch_hk_profile(hk_code: str, timeout_sec: int = 10) -> Dict[str, Any]:
    try:
        df = _safe_ak_call(ak.stock_hk_security_profile_em, symbol=hk_code, timeout_sec=timeout_sec)
        if df is None or df.empty:
            return {"hk_code": hk_code, "profile_error": "empty"}
        rec = _clean_record(df.iloc[0].to_dict())
        rec["hk_code"] = hk_code
        return rec
    except Exception as e:
        return {"hk_code": hk_code, "profile_error": str(e)}


def _load_cache(cache_file: Path, ttl_sec: int) -> Optional[List[Dict[str, Any]]]:
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        ts = float(payload.get("generated_at", 0))
        if time.time() - ts > ttl_sec:
            return None
        data = payload.get("data", [])
        if isinstance(data, list):
            return data
    except Exception:
        return None
    return None


def _save_cache(cache_file: Path, data: List[Dict[str, Any]]) -> None:
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.time(),
        "generated_at_text": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(data),
        "data": data,
    }
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_ah_dataset(workers: int = 8, timeout_sec: int = 45) -> List[Dict[str, Any]]:
    base_df = _safe_ak_call(ak.stock_zh_ah_spot_em, timeout_sec=timeout_sec)
    if base_df is None or base_df.empty:
        return []

    base_df = base_df.copy()
    # stock_zh_ah_spot_em 返回的列名
    code_col = "H股代码" if "H股代码" in base_df.columns else base_df.columns[2]  # H股代码在第3列
    name_col = "名称" if "名称" in base_df.columns else base_df.columns[1]  # 名称在第2列
    a_code_col = "A股代码" if "A股代码" in base_df.columns else base_df.columns[5]  # A股代码在第6列

    items: List[Dict[str, Any]] = []
    for _, row in base_df.iterrows():
        hk_code = _normalize_hk_code(row[code_col])
        ah_name = str(row[name_col]).strip()
        a_code = str(row[a_code_col]).strip() if a_code_col in row.index else ""
        items.append({"hk_code": hk_code, "ah_name": ah_name, "a_code": a_code})

    profile_map: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        fut_map = {ex.submit(_fetch_hk_profile, it["hk_code"], timeout_sec): it["hk_code"] for it in items}
        for fut in as_completed(fut_map):
            hk = fut_map[fut]
            try:
                profile_map[hk] = fut.result()
            except Exception as e:
                profile_map[hk] = {"hk_code": hk, "profile_error": str(e)}

    merged: List[Dict[str, Any]] = []
    for it in items:
        hk_code = it["hk_code"]
        prof = profile_map.get(hk_code, {"hk_code": hk_code, "profile_error": "missing"})
        merged.append(
            {
                "ah_name": it["ah_name"],
                "a_code": it.get("a_code", ""),
                "hk_code": hk_code,
                "security_code": prof.get("证券代码"),
                "security_name": prof.get("证券简称") or it["ah_name"],
                "list_date": prof.get("上市日期"),
                "security_type": prof.get("证券类型"),
                "board": prof.get("板块"),
                "exchange": prof.get("交易所"),
                "is_sh_connect": prof.get("是否沪港通标的"),
                "is_sz_connect": prof.get("是否深港通标的"),
                "isin": prof.get("ISIN（国际证券识别编码）"),
                "profile_error": prof.get("profile_error"),
            }
        )

    return merged


def _filter_by_date(rows: List[Dict[str, Any]], since: str, until: str) -> List[Dict[str, Any]]:
    since_dt = _parse_date(since) if since else None
    until_dt = _parse_date(until) if until else None

    if since_dt is None and until_dt is None:
        return rows

    out = []
    for r in rows:
        d = _parse_date(r.get("list_date"))
        if d is None:
            continue
        if since_dt and d < since_dt:
            continue
        if until_dt and d > until_dt:
            continue
        out.append(r)
    return out


def _print_table(rows: List[Dict[str, Any]], limit: int = 200) -> None:
    show = rows[:limit]
    if not show:
        print("无结果")
        return

    print(f"A/H 双重上市公司：{len(rows)} 条（展示前 {len(show)} 条）")
    print("-" * 140)
    print(f"{'H代码':<8} {'A股代码':<8} {'名称':<14} {'上市日期':<12} {'证券类型':<10} {'板块':<12} {'沪港通':<6} {'深港通':<6}")
    print("-" * 140)
    for r in show:
        print(
            f"{str(r.get('hk_code') or ''):<8} "
            f"{str(r.get('a_code') or ''):<8} "
            f"{str(r.get('security_name') or r.get('ah_name') or '')[:12]:<14} "
            f"{str(r.get('list_date') or '')[:10]:<12} "
            f"{str(r.get('security_type') or '')[:8]:<10} "
            f"{str(r.get('board') or '')[:10]:<12} "
            f"{str(r.get('is_sh_connect') or ''):<6} "
            f"{str(r.get('is_sz_connect') or ''):<6}"
        )


def main():
    parser = argparse.ArgumentParser(description="查询 A/H 双重上市公司列表（支持按 H 股上市日期筛选）")
    parser.add_argument("--since", default="", help="上市日期起（含），格式 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--until", default="", help="上市日期止（含），格式 YYYY-MM-DD 或 YYYYMMDD")
    parser.add_argument("--workers", type=int, default=8, help="并发数，默认 8")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存，强制刷新")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON")
    parser.add_argument("--limit", type=int, default=200, help="文本模式最多展示条数，默认 200")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    cache_file = script_dir.parent / "cache" / "ah_stocks.json"
    ttl_sec = 12 * 3600

    rows: Optional[List[Dict[str, Any]]] = None
    cache_hit = False
    if not args.no_cache:
        rows = _load_cache(cache_file, ttl_sec)
        cache_hit = rows is not None

    if rows is None:
        rows = _build_ah_dataset(workers=args.workers)
        if rows:
            _save_cache(cache_file, rows)

    filtered = _filter_by_date(rows, args.since, args.until)

    output = {
        "query": {
            "since": args.since or None,
            "until": args.until or None,
            "workers": args.workers,
            "no_cache": bool(args.no_cache),
        },
        "meta": {
            "cache_hit": cache_hit,
            "cache_file": str(cache_file),
            "total": len(rows),
            "filtered": len(filtered),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "data": filtered,
    }

    if args.output_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    print(
        f"查询完成：总计 {output['meta']['total']} 条，"
        f"筛选后 {output['meta']['filtered']} 条，"
        f"cache_hit={output['meta']['cache_hit']}"
    )
    _print_table(filtered, limit=max(1, args.limit))


if __name__ == "__main__":
    main()
