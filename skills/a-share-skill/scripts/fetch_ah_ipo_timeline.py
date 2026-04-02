#!/usr/bin/env python3
"""
A股赴港上市(IPO)时间节点查询

功能：
1. 获取A股公司港股IPO的关键时间节点
   - 递表时间（向港交所递交申请）
   - 聆讯时间（通过上市聆讯）
   - 招股时间
   - 上市日期
2. 支持2020年至今的数据查询
3. 本地缓存（默认24小时TTL）

数据源：
- 东方财富公告API：递表、聆讯公告
- akshare：港股上市日期
"""

import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    """解析日期字符串"""
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
    """规范化港股代码"""
    s = str(raw).strip().upper()
    if s.endswith(".HK"):
        s = s[:-3]
    if s.isdigit():
        return s.zfill(5)
    return s


def _load_cache(cache_file: Path, ttl_sec: int) -> Optional[Dict[str, Any]]:
    """加载缓存"""
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
    """保存缓存"""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_ah_stock_list() -> List[Dict[str, Any]]:
    """获取AH股列表"""
    try:
        df = _safe_ak_call(ak.stock_zh_ah_spot_em, timeout_sec=30)
        if df is None or df.empty:
            return []
        
        items = []
        for _, row in df.iterrows():
            hk_code = _normalize_hk_code(row.get("H股代码", ""))
            a_code = str(row.get("A股代码", "")).strip()
            name = str(row.get("名称", "")).strip()
            items.append({
                "hk_code": hk_code,
                "a_code": a_code,
                "name": name,
            })
        return items
    except Exception as e:
        print(f"获取AH股列表失败: {e}")
        return []


def _fetch_hk_profile(hk_code: str, timeout_sec: int = 15) -> Dict[str, Any]:
    """获取港股公司资料（包含上市日期）"""
    try:
        df = _safe_ak_call(ak.stock_hk_security_profile_em, symbol=hk_code, timeout_sec=timeout_sec)
        if df is None or df.empty:
            return {"hk_code": hk_code, "profile_error": "empty"}
        rec = {k: _to_native(v) for k, v in df.iloc[0].to_dict().items()}
        rec["hk_code"] = hk_code
        return rec
    except Exception as e:
        return {"hk_code": hk_code, "profile_error": str(e)}


def _search_ipo_announcements(a_code: str, start_date: str, end_date: str, page_size: int = 50) -> List[Dict[str, Any]]:
    """搜索A股公司港股IPO相关公告"""
    url = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
    
    # IPO相关关键词
    ipo_keywords = [
        'H股', '港交所', '香港上市', '境外上市', '港股', 
        '聆讯', '递表', '全球发售', '招股书', '发行H股',
        '香港联交所', '香港交易所', '境外发行', '刊发申请资料',
        '审议.*H股', 'H股.*审议', '聆讯后', '超额配售',
        'H股挂牌', 'H股公开发行', 'H股上市'
    ]
    
    all_announcements = []
    
    # 分段搜索：每次搜索6个月的时间段
    from datetime import datetime, timedelta
    
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    
    current_start = start_dt
    while current_start < end_dt:
        current_end = min(current_start + timedelta(days=180), end_dt)
        
        params = {
            'sr': -1,
            'page_size': page_size,
            'page_index': 1,
            'ann_type': 'SHA,SZA',  # 沪深A股
            'client_source': 'web',
            'f_node': 0,
            's_node': 0,
            'begin_time': current_start.strftime('%Y-%m-%d'),
            'end_time': current_end.strftime('%Y-%m-%d'),
            'stock_list': a_code,
        }
        
        try:
            resp = requests.get(url, params=params, timeout=15, headers={
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            })
            data = resp.json()
            
            announcements = data.get('data', {}).get('list', [])
            
            # 筛选IPO相关公告
            import re
            for item in announcements:
                title = item.get('title', '')
                # 使用正则匹配
                if any(re.search(kw, title) if '.*' in kw else kw in title for kw in ipo_keywords):
                    # 去重
                    art_code = item.get('art_code', '')
                    if not any(a.get('art_code') == art_code for a in all_announcements):
                        all_announcements.append({
                            'art_code': art_code,
                            'title': title,
                            'notice_date': item.get('notice_date', ''),
                            'column_name': item['columns'][0]['column_name'] if item.get('columns') else '',
                        })
            
        except Exception as e:
            pass  # 静默失败，不影响整体流程
        
        current_start = current_end + timedelta(days=1)
    
    return all_announcements


def _extract_timeline_from_announcements(announcements: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从公告中提取时间节点"""
    timeline = {
        'submit_date': None,      # 递表时间
        'hearing_date': None,     # 聆讯时间
        'prospectus_date': None,  # 招股书发布时间
        'announce_dates': [],     # 所有公告日期
    }
    
    # 按日期排序公告（从早到晚）
    sorted_announcements = sorted(
        [a for a in announcements if a.get('notice_date')],
        key=lambda x: x.get('notice_date', '')
    )
    
    import re
    for ann in sorted_announcements:
        title = ann.get('title', '')
        notice_date = ann.get('notice_date', '')
        date_str = notice_date[:10] if notice_date else None
        date_obj = _parse_date(notice_date)
        
        if date_str:
            timeline['announce_dates'].append(date_str)
        
        # 提取递表时间（取最早的）
        if any(kw in title for kw in ['递表', '递交申请', '递交H股', '发行上市申请', '刊发申请资料', '向香港联交所递交']):
            if timeline['submit_date'] is None:
                timeline['submit_date'] = date_str
            elif date_obj:
                existing = _parse_date(timeline['submit_date'])
                if existing and date_obj < existing:
                    timeline['submit_date'] = date_str
        
        # 提取聆讯时间（取最早的通过聆讯/审议日期）
        if re.search(r'(聆讯|审议.*H股|H股.*审议|通过.*上市聆讯|联交所审议)', title):
            if timeline['hearing_date'] is None:
                timeline['hearing_date'] = date_str
        
        # 提取招股书发布时间
        if any(kw in title for kw in ['招股书', '招股章程', '全球发售']):
            if timeline['prospectus_date'] is None:
                timeline['prospectus_date'] = date_str
    
    # 去重
    timeline['announce_dates'] = sorted(list(set(timeline['announce_dates'])))
    
    return timeline


def _load_ah_stocks_cache() -> Optional[List[Dict[str, Any]]]:
    """加载已有的AH股缓存数据"""
    script_dir = Path(__file__).resolve().parent
    cache_file = script_dir.parent / "cache" / "ah_stocks.json"
    if cache_file.exists():
        try:
            payload = json.loads(cache_file.read_text(encoding="utf-8"))
            return payload.get("data", [])
        except Exception:
            pass
    return None


def _build_ah_ipo_dataset(
    since_year: int = 2020,
    workers: int = 3,
    timeout_sec: int = 20,
    skip_profile: bool = False,
    progress_callback=None
) -> List[Dict[str, Any]]:
    """构建AH股IPO时间线数据集"""
    
    # 1. 尝试从已有缓存获取AH股列表（包含上市日期）
    cached_ah = _load_ah_stocks_cache()
    
    if cached_ah:
        print(f"从缓存获取到 {len(cached_ah)} 只AH股")
        ah_stocks = []
        for item in cached_ah:
            list_date = item.get("list_date")
            if list_date:
                list_date_obj = _parse_date(list_date)
                if list_date_obj and list_date_obj.year >= since_year:
                    ah_stocks.append({
                        "hk_code": item.get("hk_code", ""),
                        "a_code": item.get("a_code", ""),
                        "name": item.get("ah_name", "") or item.get("security_name", ""),
                        "list_date": list_date[:10] if len(list_date) >= 10 else list_date,
                        "profile": {
                            "证券类型": item.get("security_type"),
                            "板块": item.get("board"),
                            "是否沪港通标的": item.get("is_sh_connect"),
                            "是否深港通标的": item.get("is_sz_connect"),
                        }
                    })
        print(f"筛选出 {len(ah_stocks)} 只 {since_year} 年后上市的AH股")
    else:
        # 从akshare获取AH股列表
        ah_stocks_raw = _fetch_ah_stock_list()
        if not ah_stocks_raw:
            return []
        print(f"获取到 {len(ah_stocks_raw)} 只AH股")
        
        # 获取港股资料
        print("正在获取港股上市日期...")
        profile_map: Dict[str, Dict[str, Any]] = {}
        
        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            fut_map = {ex.submit(_fetch_hk_profile, s["hk_code"], timeout_sec): s["hk_code"] for s in ah_stocks_raw}
            for i, fut in enumerate(as_completed(fut_map)):
                hk = fut_map[fut]
                try:
                    profile_map[hk] = fut.result()
                except Exception as e:
                    profile_map[hk] = {"hk_code": hk, "profile_error": str(e)}
                
                if progress_callback:
                    progress_callback(i + 1, len(ah_stocks_raw), "获取港股资料")
                elif (i + 1) % 20 == 0:
                    print(f"  已获取 {i + 1}/{len(ah_stocks_raw)} 只港股资料")
        
        # 筛选指定年份后上市的股票
        ah_stocks = []
        for stock in ah_stocks_raw:
            hk_code = stock["hk_code"]
            profile = profile_map.get(hk_code, {})
            list_date = profile.get("上市日期")
            
            if list_date:
                list_date_obj = _parse_date(list_date)
                if list_date_obj and list_date_obj.year >= since_year:
                    stock["list_date"] = list_date[:10] if len(list_date) >= 10 else list_date
                    stock["profile"] = profile
                    ah_stocks.append(stock)
        
        print(f"筛选出 {len(ah_stocks)} 只 {since_year} 年后上市的AH股")
    
    # 4. 搜索IPO公告（并行处理）
    print("正在搜索IPO公告...")
    start_date = f"{since_year}-01-01"
    end_date = datetime.now().strftime("%Y-%m-%d")
    
    def _process_stock(stock):
        a_code = stock.get("a_code", "")
        list_date = stock.get("list_date", "")
        
        if a_code:
            # 根据上市日期推算搜索时间范围（上市前2年到上市后1个月）
            if list_date:
                list_dt = _parse_date(list_date)
                if list_dt:
                    from datetime import timedelta
                    # 上市前2年开始搜索
                    search_start = (list_dt - timedelta(days=730)).strftime("%Y-%m-%d")
                    # 到今天为止
                    search_end = datetime.now().strftime("%Y-%m-%d")
                else:
                    search_start = start_date
                    search_end = end_date
            else:
                search_start = start_date
                search_end = end_date
            
            announcements = _search_ipo_announcements(a_code, search_start, search_end)
            timeline = _extract_timeline_from_announcements(announcements)
            stock["timeline"] = timeline
            stock["announcements"] = announcements[:10]
        return stock
    
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(_process_stock, stock): stock for stock in ah_stocks}
        for i, fut in enumerate(as_completed(futures)):
            try:
                fut.result()
            except Exception:
                pass
            
            if (i + 1) % 10 == 0:
                print(f"  已搜索 {i + 1}/{len(ah_stocks)} 只股票的公告")
    
    print(f"  已搜索 {len(ah_stocks)} 只股票的公告")
    
    # 5. 构建最终数据
    result = []
    for stock in ah_stocks:
        hk_code = stock["hk_code"]
        profile = stock.get("profile", {})
        timeline = stock.get("timeline", {})
        
        result.append({
            "a_code": stock.get("a_code", ""),
            "hk_code": hk_code,
            "name": stock.get("name", ""),
            "submit_date": timeline.get("submit_date"),
            "hearing_date": timeline.get("hearing_date"),
            "prospectus_date": timeline.get("prospectus_date"),
            "list_date": stock.get("list_date"),
            "announce_count": len(timeline.get("announce_dates", [])),
            "announce_dates": timeline.get("announce_dates", [])[:5],  # 只保留前5条
            "security_type": profile.get("证券类型"),
            "board": profile.get("板块"),
            "is_sh_connect": profile.get("是否沪港通标的"),
            "is_sz_connect": profile.get("是否深港通标的"),
        })
    
    # 按上市日期排序
    result.sort(key=lambda x: x.get("list_date") or "9999-99-99", reverse=True)
    
    return result


def _filter_rows(rows: List[Dict[str, Any]], code: str = "", name: str = "", keyword: str = "") -> List[Dict[str, Any]]:
    """按A股代码/港股代码/名称/关键词过滤"""
    code = (code or "").strip().upper()
    name = (name or "").strip().lower()
    keyword = (keyword or "").strip().lower()

    if not code and not name and not keyword:
        return rows

    out: List[Dict[str, Any]] = []
    for r in rows:
        a_code = str(r.get("a_code") or "").upper()
        hk_code = str(r.get("hk_code") or "").upper()
        stock_name = str(r.get("name") or "")
        stock_name_l = stock_name.lower()

        if code and code not in {a_code, hk_code, hk_code.zfill(5)}:
            continue
        if name and name not in stock_name_l:
            continue

        if keyword:
            corpus = " ".join([
                stock_name_l,
                str(r.get("submit_date") or ""),
                str(r.get("hearing_date") or ""),
                str(r.get("prospectus_date") or ""),
                str(r.get("list_date") or ""),
            ]).lower()
            if keyword not in corpus:
                continue

        out.append(r)

    return out


def _print_table(rows: List[Dict[str, Any]], limit: int = 50) -> None:
    """打印表格"""
    show = rows[:limit]
    if not show:
        print("无结果")
        return

    print(f"A股赴港上市时间节点：{len(rows)} 条（展示前 {len(show)} 条）")
    print("-" * 140)
    print(f"{'A股代码':<8} {'H股代码':<8} {'名称':<10} {'递表日期':<12} {'聆讯日期':<12} {'上市日期':<12} {'公告数':<6}")
    print("-" * 140)
    for r in show:
        print(
            f"{str(r.get('a_code') or ''):<8} "
            f"{str(r.get('hk_code') or ''):<8} "
            f"{str(r.get('name') or '')[:8]:<10} "
            f"{str(r.get('submit_date') or '-'):<12} "
            f"{str(r.get('hearing_date') or '-'):<12} "
            f"{str(r.get('list_date') or '-'):<12} "
            f"{str(r.get('announce_count') or 0):<6}"
        )


def main():
    parser = argparse.ArgumentParser(description="查询A股赴港上市(IPO)时间节点")
    parser.add_argument("--since", type=int, default=2020, help="起始年份，默认2020")
    parser.add_argument("--workers", type=int, default=3, help="并发数，默认3")
    parser.add_argument("--no-cache", action="store_true", help="跳过缓存，强制刷新")
    parser.add_argument("--skip-profile", action="store_true", help="跳过获取港股资料，使用已有缓存")
    parser.add_argument("--code", default="", help="按A股/港股代码过滤，如 301171 或 09995")
    parser.add_argument("--name", default="", help="按名称过滤，如 易点天下")
    parser.add_argument("--keyword", default="", help="按关键词过滤")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出JSON")
    parser.add_argument("--limit", type=int, default=50, help="文本模式最多展示条数，默认50")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    cache_file = script_dir.parent / "cache" / "ah_ipo_timeline.json"
    ttl_sec = 24 * 3600  # 24小时缓存

    cache_hit = False
    cached_data = None
    
    if not args.no_cache:
        cached_data = _load_cache(cache_file, ttl_sec)
        cache_hit = cached_data is not None

    if cached_data:
        rows = cached_data.get("data", [])
        meta = cached_data.get("meta", {})
    else:
        rows = _build_ah_ipo_dataset(
            since_year=args.since,
            workers=args.workers,
            skip_profile=args.skip_profile,
        )
        meta = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "since_year": args.since,
            "total": len(rows),
        }
        _save_cache(cache_file, {"generated_at": time.time(), "meta": meta, "data": rows})

    filtered_rows = _filter_rows(rows, code=args.code, name=args.name, keyword=args.keyword)

    output = {
        "query": {
            "since_year": args.since,
            "workers": args.workers,
            "no_cache": bool(args.no_cache),
            "code": args.code or None,
            "name": args.name or None,
            "keyword": args.keyword or None,
        },
        "meta": {
            **meta,
            "cache_hit": cache_hit,
            "cache_file": str(cache_file),
            "filtered": len(filtered_rows),
        },
        "data": filtered_rows,
    }

    if args.output_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    print(
        f"查询完成：总计 {output['meta']['total']} 条，"
        f"筛选后 {output['meta']['filtered']} 条，"
        f"cache_hit={output['meta']['cache_hit']}"
    )
    _print_table(filtered_rows, limit=max(1, args.limit))


if __name__ == "__main__":
    main()
