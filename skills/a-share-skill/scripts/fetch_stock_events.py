#!/usr/bin/env python3
"""
个股事件信息查询脚本
覆盖：
1) 业绩/预告
2) 增减持/回购
3) 监管事项
4) 重大订单合同
5) 舆情热度方向

依赖：pip install akshare pandas
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# 检测 --json 参数，在 import akshare 之前禁用 tqdm 防止进度条污染 stdout
if "--json" in sys.argv:
    os.environ["TQDM_DISABLE"] = "1"

import akshare as ak
import pandas as pd


class _CallTimeout(Exception):
    pass


def _safe_ak_call(fn, *args, timeout_sec: int = 8, **kwargs):
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


def _remaining_seconds(deadline_ts: float) -> int:
    return max(0, int(deadline_ts - time.time()))


def normalize_code(code: str) -> str:
    c = code.strip()
    if c.lower().startswith(("sh", "sz")):
        c = c[2:]
    if "." in c:
        parts = c.split(".")
        if parts[-1].isdigit():
            c = parts[-1]
        elif parts[0].isdigit():
            c = parts[0]
    if c.isdigit() and len(c) <= 6:
        return c.zfill(6)
    return c


_STOCK_NAME_CACHE: Dict[str, str] = {}
_STOCK_NAME_CACHE_TS: float = 0.0
_STOCK_NAME_CACHE_LOCK = threading.Lock()
_STOCK_NAME_CACHE_TTL_SECONDS = 12 * 3600
_STOCK_NAME_CACHE_FILE = Path(__file__).resolve().parents[3] / "cache" / "stock_name_map.json"


def _load_stock_name_cache_from_disk() -> None:
    global _STOCK_NAME_CACHE, _STOCK_NAME_CACHE_TS
    try:
        if not _STOCK_NAME_CACHE_FILE.exists():
            return
        obj = json.loads(_STOCK_NAME_CACHE_FILE.read_text(encoding="utf-8"))
        data = obj.get("data") if isinstance(obj, dict) else None
        updated_at = float(obj.get("updated_at", 0)) if isinstance(obj, dict) else 0.0
        if isinstance(data, dict) and data:
            with _STOCK_NAME_CACHE_LOCK:
                _STOCK_NAME_CACHE = {str(k).zfill(6): str(v) for k, v in data.items()}
                _STOCK_NAME_CACHE_TS = updated_at if updated_at > 0 else time.time()
    except Exception:
        pass


def _save_stock_name_cache_to_disk(mapping: Dict[str, str], updated_at: float) -> None:
    try:
        _STOCK_NAME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": updated_at,
            "ttl_sec": _STOCK_NAME_CACHE_TTL_SECONDS,
            "size": len(mapping),
            "data": mapping,
        }
        _STOCK_NAME_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_stock_name_cache(deadline_ts: float, ttl_seconds: int = _STOCK_NAME_CACHE_TTL_SECONDS) -> Dict[str, str]:
    """加载并缓存全市场股票简称映射（内存+落盘），避免每只股票都拉一次全市场列表。"""
    global _STOCK_NAME_CACHE, _STOCK_NAME_CACHE_TS

    # 先尝试从磁盘加载
    if not _STOCK_NAME_CACHE:
        _load_stock_name_cache_from_disk()

    now = time.time()
    with _STOCK_NAME_CACHE_LOCK:
        if _STOCK_NAME_CACHE and (now - _STOCK_NAME_CACHE_TS) < ttl_seconds:
            return _STOCK_NAME_CACHE

    remain = _remaining_seconds(deadline_ts)
    if remain <= 1:
        return _STOCK_NAME_CACHE

    try:
        df = _safe_ak_call(ak.stock_zh_a_spot_em, timeout_sec=min(8, remain))
        if df is not None and not df.empty and "代码" in df.columns and "名称" in df.columns:
            mapping = {
                str(row["代码"]).zfill(6): str(row["名称"])
                for _, row in df[["代码", "名称"]].iterrows()
            }
            now_ts = time.time()
            with _STOCK_NAME_CACHE_LOCK:
                _STOCK_NAME_CACHE = mapping
                _STOCK_NAME_CACHE_TS = now_ts
            _save_stock_name_cache_to_disk(mapping, now_ts)
            return mapping
    except Exception:
        pass
    return _STOCK_NAME_CACHE


def get_stock_name(code6: str, deadline_ts: float) -> Optional[str]:
    """通过股票代码获取股票简称（带缓存）。"""
    mapping = _load_stock_name_cache(deadline_ts)
    return mapping.get(code6)


def to_hot_symbol(code6: str) -> str:
    if code6.startswith("6"):
        return f"SH{code6}"
    return f"SZ{code6}"


def _to_records(df: pd.DataFrame) -> List[Dict]:
    if df is None or df.empty:
        return []
    safe_df = df.copy()
    for col in safe_df.columns:
        if "日期" in str(col) or str(col).endswith("时间"):
            try:
                safe_df[col] = safe_df[col].astype(str)
            except Exception:
                pass
    return safe_df.to_dict(orient="records")


def _parse_dates(dates: List[str]) -> List[str]:
    out = []
    for d in dates:
        s = d.strip()
        if re.fullmatch(r"\d{8}", s):
            out.append(s)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            out.append(s.replace("-", ""))
    return out


def _default_dates(days: int = 365) -> List[str]:
    """生成财报季日期列表（季度末日期：0331, 0630, 0930, 1231）
    
    业绩预告/快报 API 需要使用财报季日期，如 20260331, 20251231 等。
    非财报季日期（如 20260401）会导致 API 返回错误。
    """
    today = datetime.now().date()
    current_year = today.year
    current_month = today.month
    
    # 财报季结束月份：3月、6月、9月、12月
    quarter_ends = [3, 6, 9, 12]
    quarter_end_days = {3: 31, 6: 30, 9: 30, 12: 31}
    
    dates = []
    
    # 从当前季度往前推算
    for year_offset in range(0, 4):  # 查询最近4年的财报
        target_year = current_year - year_offset
        for month in reversed(quarter_ends):
            # 如果是当前年份，只查询已过去的季度
            if target_year == current_year and month > current_month:
                continue
            date_str = f"{target_year}{month:02d}{quarter_end_days[month]:02d}"
            dates.append(date_str)
            
            # 如果已经超过 days 天的范围，停止
            date_obj = datetime.strptime(date_str, "%Y%m%d").date()
            if (today - date_obj).days > days:
                break
        else:
            continue
        break
    
    return dates[:8]  # 最多返回8个财报季日期


def query_performance(code6: str, dates: List[str], limit: int, deadline_ts: float) -> Dict:
    yjyg_rows = []
    yjbb_rows = []
    financial_abstract_rows = []

    # 1. 尝试从业绩预告/快报获取数据
    for d in dates:
        if _remaining_seconds(deadline_ts) <= 1:
            break
        try:
            df = _safe_ak_call(ak.stock_yjyg_em, date=d, timeout_sec=min(8, _remaining_seconds(deadline_ts)))
            if df is not None and not df.empty and "股票代码" in df.columns:
                filtered = df[df["股票代码"].astype(str).str.zfill(6) == code6].copy()
                if not filtered.empty:
                    yjyg_rows.extend(_to_records(filtered.head(limit)))
        except Exception:
            pass

        if _remaining_seconds(deadline_ts) <= 1:
            break
        try:
            df = _safe_ak_call(ak.stock_yjbb_em, date=d, timeout_sec=min(8, _remaining_seconds(deadline_ts)))
            if df is not None and not df.empty and "股票代码" in df.columns:
                filtered = df[df["股票代码"].astype(str).str.zfill(6) == code6].copy()
                if not filtered.empty:
                    yjbb_rows.extend(_to_records(filtered.head(limit)))
        except Exception:
            pass

        if yjyg_rows or yjbb_rows:
            break

    # 2. 如果业绩预告/快报都没有数据，尝试从财务摘要获取
    #    这对于大公司（如茅台）很重要，它们可能不发布业绩预告/快报
    if not yjyg_rows and not yjbb_rows and _remaining_seconds(deadline_ts) > 3:
        try:
            df = _safe_ak_call(ak.stock_financial_abstract, symbol=code6, timeout_sec=min(8, _remaining_seconds(deadline_ts)))
            if df is not None and not df.empty:
                # 提取最近一期的财报数据
                # 列格式：选项, 指标, 20250930, 20250630, ...
                date_cols = [c for c in df.columns if c not in ["选项", "指标"]]
                if date_cols:
                    latest_col = date_cols[0]  # 最近一期
                    # 转换为记录格式
                    abstract_data = {
                        "报告期": latest_col,
                        "数据来源": "财务摘要",
                    }
                    # 提取关键指标
                    key_indicators = [
                        "归母净利润", "营业总收入", "净利润", "扣非净利润", 
                        "基本每股收益", "每股净资产", "净资产收益率(ROE)", 
                        "毛利率", "销售净利率", "经营现金流量净额"
                    ]
                    for _, row in df.iterrows():
                        indicator = row.get("指标", "")
                        if indicator in key_indicators and latest_col in df.columns:
                            val = row.get(latest_col)
                            if pd.notna(val):
                                abstract_data[indicator] = val
                    
                    if len(abstract_data) > 2:  # 有实际数据
                        financial_abstract_rows = [abstract_data]
        except Exception:
            pass

    return {
        "category": "业绩/预告",
        "forecast": yjyg_rows,
        "express": yjbb_rows,
        "financial_abstract": financial_abstract_rows,
        "count": len(yjyg_rows) + len(yjbb_rows) + len(financial_abstract_rows),
    }


def _fetch_news_by_keywords(keywords: List[str], limit: int, deadline_ts: float) -> pd.DataFrame:
    """多关键词检索新闻，合并去重"""
    all_news = []
    for kw in keywords[:2]:
        if _remaining_seconds(deadline_ts) <= 1:
            break
        try:
            df = _safe_ak_call(ak.stock_news_em, symbol=kw, timeout_sec=min(6, _remaining_seconds(deadline_ts)))
            if df is not None and not df.empty:
                df["_keyword"] = kw
                all_news.append(df)
        except Exception:
            pass

    if not all_news:
        return pd.DataFrame()

    combined = pd.concat(all_news, ignore_index=True)

    # 按新闻链接去重
    if "新闻链接" in combined.columns:
        combined = combined.drop_duplicates(subset=["新闻链接"], keep="first")
    elif "新闻标题" in combined.columns:
        combined = combined.drop_duplicates(subset=["新闻标题"], keep="first")

    if "发布时间" in combined.columns:
        combined = combined.sort_values(by="发布时间", ascending=False)

    return combined.head(limit)


def _filter_news_by_keywords(df: pd.DataFrame, keywords: List[str], limit: int) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    text_cols = [c for c in ["新闻标题", "新闻内容", "文章来源"] if c in df.columns]
    if not text_cols:
        return pd.DataFrame()

    pattern = "|".join(re.escape(k) for k in keywords)
    mask = pd.Series(False, index=df.index)
    for col in text_cols:
        mask = mask | df[col].astype(str).str.contains(pattern, case=False, na=False, regex=True)

    out = df[mask].copy()
    if "发布时间" in out.columns:
        out = out.sort_values(by="发布时间", ascending=False)
    return out.head(limit)


def query_news_categories(code6: str, stock_name: Optional[str], limit: int, deadline_ts: float) -> Dict:
    # 构建检索关键词列表：代码 + 公司名（如有）
    search_keywords = [code6]
    if stock_name:
        # 添加公司简称和全称
        search_keywords.append(stock_name)
        # 如果公司名有后缀（如"科技"、"股份"），也尝试简称
        short_name = re.sub(r"(科技|股份|集团|电子|信息|技术|实业|发展|投资|控股)$", "", stock_name)
        if short_name and short_name != stock_name:
            search_keywords.append(short_name)

    # 多关键词检索并合并
    news_df = _fetch_news_by_keywords(search_keywords, limit * 2, deadline_ts)

    holder_buyback_kw = ["增持", "减持", "回购", "回购股份"]
    regulatory_kw = ["监管", "问询", "警示", "立案", "处罚", "关注函", "监管函", "公告", "披露"]
    contract_kw = ["重大合同", "重大订单", "中标", "订单", "签订合同", "框架协议", "项目", "签约", "合作", "在手订单", "拉货"]

    holder_buyback = _filter_news_by_keywords(news_df, holder_buyback_kw, limit)
    regulatory = _filter_news_by_keywords(news_df, regulatory_kw, limit)
    contracts = _filter_news_by_keywords(news_df, contract_kw, limit)
    contract_source = "东方财富-个股新闻关键词"
    if contracts.empty and news_df is not None and not news_df.empty:
        contracts = news_df.head(limit).copy()
        contract_source = "东方财富-个股新闻兜底"

    return {
        "holder_change_buyback": {
            "category": "增减持/回购",
            "items": _to_records(holder_buyback),
            "count": len(holder_buyback),
            "source": f"东方财富-多关键词检索({'+'.join(search_keywords)})",
        },
        "regulatory": {
            "category": "监管事项",
            "items": _to_records(regulatory),
            "count": len(regulatory),
            "source": f"东方财富-多关键词检索({'+'.join(search_keywords)})",
        },
        "major_contracts": {
            "category": "重大订单合同",
            "items": _to_records(contracts),
            "count": len(contracts),
            "source": contract_source,
        },
    }


def query_sentiment(code6: str, limit: int, deadline_ts: float) -> Dict:
    symbol = to_hot_symbol(code6)
    rank_records = []
    detail_records = []
    baidu_records = []

    if _remaining_seconds(deadline_ts) > 1:
        try:
            rank_df = _safe_ak_call(ak.stock_hot_rank_em, timeout_sec=min(6, _remaining_seconds(deadline_ts)))
            if rank_df is not None and not rank_df.empty:
                code_col = "代码" if "代码" in rank_df.columns else None
                if code_col:
                    filtered = rank_df[rank_df[code_col].astype(str).str.zfill(6) == code6].copy()
                    rank_records = _to_records(filtered.head(1))
        except Exception:
            pass

    if _remaining_seconds(deadline_ts) > 1:
        try:
            detail_df = _safe_ak_call(ak.stock_hot_rank_detail_em, symbol=symbol, timeout_sec=min(6, _remaining_seconds(deadline_ts)))
            if detail_df is not None and not detail_df.empty:
                if "时间" in detail_df.columns:
                    detail_df = detail_df.sort_values(by="时间", ascending=False)
                detail_records = _to_records(detail_df.head(limit))
        except Exception:
            pass

    if not rank_records and _remaining_seconds(deadline_ts) > 1:
        try:
            latest_df = _safe_ak_call(ak.stock_hot_rank_latest_em, symbol=symbol, timeout_sec=min(6, _remaining_seconds(deadline_ts)))
            if latest_df is not None and not latest_df.empty:
                rank_records = _to_records(latest_df.head(1))
        except Exception:
            pass

    if not detail_records and _remaining_seconds(deadline_ts) > 1:
        try:
            baidu_df = _safe_ak_call(
                ak.stock_hot_search_baidu,
                symbol="A股",
                date=datetime.now().strftime("%Y%m%d"),
                time="今日",
                timeout_sec=min(6, _remaining_seconds(deadline_ts)),
            )
            if baidu_df is not None and not baidu_df.empty and "名称/代码" in baidu_df.columns:
                filtered = baidu_df[baidu_df["名称/代码"].astype(str).str.contains(code6, na=False)].copy()
                baidu_records = _to_records(filtered.head(limit))
        except Exception:
            pass

    direction = "未知"
    if detail_records and "排名" in detail_records[0]:
        try:
            ranks = [float(item["排名"]) for item in detail_records if str(item.get("排名", "")).strip() != ""]
            if len(ranks) >= 2:
                if ranks[0] < ranks[-1]:
                    direction = "热度上升"
                elif ranks[0] > ranks[-1]:
                    direction = "热度下降"
                else:
                    direction = "热度持平"
        except Exception:
            pass

    return {
        "category": "舆情热度方向",
        "rank_snapshot": rank_records,
        "rank_trend": detail_records,
        "baidu_hot": baidu_records,
        "direction": direction,
        "count": len(rank_records) + len(detail_records) + len(baidu_records),
    }


def build_payload(code: str, stock_name: Optional[str], dates: List[str], limit: int, max_seconds: int, skip_sentiment: bool) -> Dict:
    code6 = normalize_code(code)
    # 事件查询超时上限：60s（避免长时间阻塞）
    budget = min(60, max(8, int(max_seconds)))
    deadline_ts = time.time() + budget

    # 自动获取股票名称（如果未提供）
    if not stock_name:
        stock_name = get_stock_name(code6, deadline_ts)

    perf = {
        "category": "业绩/预告",
        "forecast": [],
        "express": [],
        "count": 0,
    }
    news_blocks = {
        "holder_change_buyback": {"category": "增减持/回购", "items": [], "count": 0, "source": ""},
        "regulatory": {"category": "监管事项", "items": [], "count": 0, "source": ""},
        "major_contracts": {"category": "重大订单合同", "items": [], "count": 0, "source": ""},
    }
    sentiment = {
        "category": "舆情热度方向",
        "rank_snapshot": [],
        "rank_trend": [],
        "baidu_hot": [],
        "direction": "未知",
        "count": 0,
    }

    # 三大模块并行：业绩 / 新闻分类 / 舆情
    workers = 3 if not skip_sentiment else 2
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_perf = ex.submit(query_performance, code6, dates, limit, deadline_ts)
        fut_news = ex.submit(query_news_categories, code6, stock_name, limit, deadline_ts)
        fut_sent = None
        if not skip_sentiment and _remaining_seconds(deadline_ts) > 1:
            fut_sent = ex.submit(query_sentiment, code6, limit, deadline_ts)

        for key, fut in [("perf", fut_perf), ("news", fut_news), ("sent", fut_sent)]:
            if fut is None:
                continue
            remain = max(1, _remaining_seconds(deadline_ts))
            try:
                val = fut.result(timeout=remain)
                if key == "perf":
                    perf = val
                elif key == "news":
                    news_blocks = val
                elif key == "sent":
                    sentiment = val
            except FuturesTimeoutError:
                pass
            except Exception:
                pass

    return {
        "code": code6,
        "name": stock_name,
        "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "performance": perf,
        "holder_change_buyback": news_blocks["holder_change_buyback"],
        "regulatory": news_blocks["regulatory"],
        "major_contracts": news_blocks["major_contracts"],
        "sentiment": sentiment,
    }


def print_text(payload: Dict, preview: int) -> None:
    name_info = f" ({payload['name']})" if payload.get("name") else ""
    print(f"【个股事件信息】{payload['code']}{name_info}  查询时间：{payload['queried_at']}")

    perf = payload["performance"]
    print(f"\n1) 业绩/预告：{perf['count']} 条")
    for item in perf["forecast"][:preview]:
        print(f"  - 预告 | {item.get('公告日期', '')} | {item.get('股票简称', '')} | {item.get('预告类型', '')}")
    for item in perf["express"][:preview]:
        print(f"  - 快报 | {item.get('最新公告日期', '')} | {item.get('股票简称', '')}")
    for item in perf.get("financial_abstract", [])[:preview]:
        print(f"  - 财报摘要 | 报告期: {item.get('报告期', '')} | 归母净利润: {item.get('归母净利润', 'N/A')} | 营收: {item.get('营业总收入', 'N/A')}")
        if item.get("基本每股收益"):
            print(f"    | 每股收益: {item.get('基本每股收益')} | ROE: {item.get('净资产收益率(ROE)', 'N/A')} | 毛利率: {item.get('毛利率', 'N/A')}")

    hc = payload["holder_change_buyback"]
    print(f"\n2) 增减持/回购：{hc['count']} 条")
    for item in hc["items"][:preview]:
        print(f"  - {item.get('发布时间', '')} | {item.get('新闻标题', '')}")

    rg = payload["regulatory"]
    print(f"\n3) 监管事项：{rg['count']} 条")
    for item in rg["items"][:preview]:
        print(f"  - {item.get('发布时间', '')} | {item.get('新闻标题', '')}")

    mc = payload["major_contracts"]
    print(f"\n4) 重大订单合同：{mc['count']} 条")
    for item in mc["items"][:preview]:
        print(f"  - {item.get('发布时间', '')} | {item.get('新闻标题', '')}")

    st = payload["sentiment"]
    print(f"\n5) 舆情热度方向：{st['direction']}（记录数 {st['count']}）")
    for item in st["rank_snapshot"][:1]:
        print(f"  - 当前热榜快照：{item}")
    for item in st["rank_trend"][:preview]:
        print(f"  - 趋势 | {item.get('时间', '')} | 排名: {item.get('排名', '')} | 新晋粉丝: {item.get('新晋粉丝', '')}")
    for item in st.get("baidu_hot", [])[:preview]:
        print(f"  - 百度热度 | {item.get('名称/代码', '')} | 综合热度: {item.get('综合热度', '')}")


def _parse_code_list(raw: str) -> List[str]:
    if not raw:
        return []
    out = []
    seen = set()
    for x in re.split(r"[,\s]+", raw.strip()):
        if not x:
            continue
        code = normalize_code(x)
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="查询个股业绩、增减持/回购、监管、重大合同、舆情热度")
    parser.add_argument("--code", required=False, help="股票代码，如 600519 / sh600519 / sh.600519")
    parser.add_argument("--batch-codes", default="", help="批量股票代码，逗号或空格分隔")
    parser.add_argument("--workers", type=int, default=5, help="批量模式并发数，默认5")
    parser.add_argument("--name", default="", help="股票简称，如 胜宏科技（用于增强新闻检索）")
    parser.add_argument("--dates", default="", help="业绩查询日期，逗号分隔，支持 YYYYMMDD 或 YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=50, help="每个类别最多返回条数，默认 50")
    parser.add_argument("--preview", type=int, default=5, help="文本模式每类预览条数，默认 5")
    parser.add_argument("--max-seconds", type=int, default=60, help="整体最大执行秒数，默认 60（上限60）")
    parser.add_argument("--skip-sentiment", action="store_true", help="跳过舆情模块，提升稳定性和速度")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON")
    args = parser.parse_args()

    dates = _parse_dates(args.dates.split(",")) if args.dates.strip() else _default_dates(120)

    batch_codes = _parse_code_list(args.batch_codes)
    if batch_codes:
        start_ts = time.time()
        workers = max(1, int(args.workers or 5))
        results: List[Dict] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(
                    build_payload,
                    code,
                    None,
                    dates,
                    args.limit,
                    args.max_seconds,
                    args.skip_sentiment,
                ): code
                for code in batch_codes
            }
            for f in as_completed(futs):
                code = futs[f]
                try:
                    payload = f.result()
                except Exception as e:
                    payload = {
                        "code": code,
                        "name": None,
                        "queried_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "error": str(e),
                    }
                results.append(payload)

        order = {c: i for i, c in enumerate(batch_codes)}
        results.sort(key=lambda x: order.get(x.get("code", ""), 10**9))

        if args.output_json:
            print(json.dumps({
                "meta": {
                    "requested": len(batch_codes),
                    "workers": workers,
                    "elapsed_sec": round(time.time() - start_ts, 2),
                    "max_seconds_per_stock": min(60, max(8, int(args.max_seconds))),
                },
                "results": results,
            }, ensure_ascii=False, indent=2))
            return

        print(f"【批量个股事件】请求{len(batch_codes)}只 并发={workers} 耗时={round(time.time() - start_ts, 2)}s")
        for p in results:
            print(f"- {p.get('code')} {p.get('name') or ''} | 事件总数: {p.get('performance', {}).get('count', 0) + p.get('holder_change_buyback', {}).get('count', 0) + p.get('regulatory', {}).get('count', 0) + p.get('major_contracts', {}).get('count', 0) + p.get('sentiment', {}).get('count', 0)}")
        return

    if not args.code:
        print("请通过 --code 或 --batch-codes 指定股票代码")
        sys.exit(1)

    stock_name = args.name.strip() if args.name.strip() else None
    payload = build_payload(args.code, stock_name, dates, args.limit, args.max_seconds, args.skip_sentiment)

    if args.output_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print_text(payload, args.preview)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        sys.exit(130)
