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
import re
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import akshare as ak
import pandas as pd


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


def get_stock_name(code6: str) -> Optional[str]:
    """通过股票代码获取股票简称"""
    try:
        # 尝试从实时行情获取股票名称
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            code_col = "代码" if "代码" in df.columns else None
            name_col = "名称" if "名称" in df.columns else None
            if code_col and name_col:
                match = df[df[code_col].astype(str).str.zfill(6) == code6]
                if not match.empty:
                    return str(match.iloc[0][name_col])
    except Exception:
        pass
    return None


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


def _default_dates(days: int = 120) -> List[str]:
    today = datetime.now().date()
    dates = []
    for i in range(0, days, 30):
        d = today - timedelta(days=i)
        dates.append(d.strftime("%Y%m%d"))
    return dates


def query_performance(code6: str, dates: List[str], limit: int) -> Dict:
    yjyg_rows = []
    yjbb_rows = []

    for d in dates:
        try:
            df = ak.stock_yjyg_em(date=d)
            if df is not None and not df.empty and "股票代码" in df.columns:
                filtered = df[df["股票代码"].astype(str).str.zfill(6) == code6].copy()
                if not filtered.empty:
                    yjyg_rows.extend(_to_records(filtered.head(limit)))
        except Exception:
            pass

        try:
            df = ak.stock_yjbb_em(date=d)
            if df is not None and not df.empty and "股票代码" in df.columns:
                filtered = df[df["股票代码"].astype(str).str.zfill(6) == code6].copy()
                if not filtered.empty:
                    yjbb_rows.extend(_to_records(filtered.head(limit)))
        except Exception:
            pass

        if yjyg_rows or yjbb_rows:
            break

    return {
        "category": "业绩/预告",
        "forecast": yjyg_rows,
        "express": yjbb_rows,
        "count": len(yjyg_rows) + len(yjbb_rows),
    }


def _fetch_news_by_keywords(keywords: List[str], limit: int = 100) -> pd.DataFrame:
    """多关键词检索新闻，合并去重"""
    all_news = []
    for kw in keywords:
        try:
            df = ak.stock_news_em(symbol=kw)
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


def query_news_categories(code6: str, stock_name: Optional[str], limit: int) -> Dict:
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
    news_df = _fetch_news_by_keywords(search_keywords, limit * 3)

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


def query_sentiment(code6: str, limit: int) -> Dict:
    symbol = to_hot_symbol(code6)
    rank_records = []
    detail_records = []
    baidu_records = []

    try:
        rank_df = ak.stock_hot_rank_em()
        if rank_df is not None and not rank_df.empty:
            code_col = "代码" if "代码" in rank_df.columns else None
            if code_col:
                filtered = rank_df[rank_df[code_col].astype(str).str.zfill(6) == code6].copy()
                rank_records = _to_records(filtered.head(1))
    except Exception:
        pass

    try:
        detail_df = ak.stock_hot_rank_detail_em(symbol=symbol)
        if detail_df is not None and not detail_df.empty:
            if "时间" in detail_df.columns:
                detail_df = detail_df.sort_values(by="时间", ascending=False)
            detail_records = _to_records(detail_df.head(limit))
    except Exception:
        pass

    if not rank_records:
        try:
            latest_df = ak.stock_hot_rank_latest_em(symbol=symbol)
            if latest_df is not None and not latest_df.empty:
                rank_records = _to_records(latest_df.head(1))
        except Exception:
            pass

    if not detail_records:
        try:
            baidu_df = ak.stock_hot_search_baidu(symbol="A股", date=datetime.now().strftime("%Y%m%d"), time="今日")
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


def build_payload(code: str, stock_name: Optional[str], dates: List[str], limit: int) -> Dict:
    code6 = normalize_code(code)

    # 自动获取股票名称（如果未提供）
    if not stock_name:
        stock_name = get_stock_name(code6)

    perf = query_performance(code6, dates, limit)
    news_blocks = query_news_categories(code6, stock_name, limit)
    sentiment = query_sentiment(code6, limit)

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


def main() -> None:
    parser = argparse.ArgumentParser(description="查询个股业绩、增减持/回购、监管、重大合同、舆情热度")
    parser.add_argument("--code", required=True, help="股票代码，如 600519 / sh600519 / sh.600519")
    parser.add_argument("--name", default="", help="股票简称，如 胜宏科技（用于增强新闻检索）")
    parser.add_argument("--dates", default="", help="业绩查询日期，逗号分隔，支持 YYYYMMDD 或 YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=50, help="每个类别最多返回条数，默认 50")
    parser.add_argument("--preview", type=int, default=5, help="文本模式每类预览条数，默认 5")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出 JSON")
    args = parser.parse_args()

    dates = _parse_dates(args.dates.split(",")) if args.dates.strip() else _default_dates(120)
    stock_name = args.name.strip() if args.name.strip() else None
    payload = build_payload(args.code, stock_name, dates, args.limit)

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
