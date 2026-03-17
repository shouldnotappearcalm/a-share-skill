#!/usr/bin/env python3
"""
A股实时行情数据脚本
数据源：东方财富 / 新浪财经（通过 akshare）+ Ashare（腾讯/新浪实时K线）

依赖安装：pip install akshare ashares pandas requests

用法示例：
  python3 fetch_realtime.py --quote 600519
  python3 fetch_realtime.py --kline 600519 --freq 1d --count 30
  python3 fetch_realtime.py --index
  python3 fetch_realtime.py --hot-sectors --top 20
  python3 fetch_realtime.py --north-money
  python3 fetch_realtime.py --lhb --start 20260310 --end 20260318
  python3 fetch_realtime.py --limit-stats
  python3 fetch_realtime.py --limit-up-pool --date 20260318
  python3 fetch_realtime.py --fund-flow 600519
  python3 fetch_realtime.py --consecutive-limit
"""

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timedelta

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import akshare as ak


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.eastmoney.com",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def normalize_code(code: str) -> str:
    code = code.strip()
    if "." in code:
        parts = code.split(".")
        prefix, suffix = parts[0].lower(), parts[1].upper()
        if prefix in ("sh", "sz") and suffix.isdigit():
            return f"{prefix}{suffix}"
        if suffix == "XSHG":
            return f"sh{prefix}"
        if suffix == "XSHE":
            return f"sz{prefix}"
    if code.lower().startswith(("sh", "sz")):
        return code.lower()
    if code.isdigit():
        return f"sh{code}" if code.startswith("6") else f"sz{code}"
    return code


def _fetch_url(url: str, extra_headers: dict = None, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    if extra_headers:
        for k, v in extra_headers.items():
            req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _get_eastmoney_quote(code: str) -> dict:
    normalized = normalize_code(code)
    market = 1 if normalized.startswith("sh") else 0
    clean = normalized[2:]
    url = (
        f"http://push2.eastmoney.com/api/qt/stock/get"
        f"?secid={market}.{clean}"
        f"&fields=f43,f44,f45,f46,f47,f48,f57,f58,f60,f107,f169,f170,f171"
    )
    raw = _fetch_url(url)
    if raw:
        try:
            obj = json.loads(raw)
            d = obj.get("data", {}) or {}
            if d.get("f43"):
                prev = d["f60"] / 100
                curr = d["f43"] / 100
                return {
                    "代码": code,
                    "名称": d.get("f58", ""),
                    "最新价": round(curr, 2),
                    "涨跌额": round(d["f169"] / 100, 2),
                    "涨跌幅(%)": round(d["f170"] / 100, 2),
                    "今开": round(d["f46"] / 100, 2),
                    "最高": round(d["f44"] / 100, 2),
                    "最低": round(d["f45"] / 100, 2),
                    "昨收": round(prev, 2),
                    "成交量(手)": d.get("f47", 0),
                    "成交额(亿)": round(d.get("f48", 0) / 1e8, 2),
                    "换手率(%)": round(d.get("f171", 0) / 100, 2),
                    "数据源": "东方财富",
                    "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
        except Exception:
            pass
    return {}


def cmd_quote(code: str, output_json: bool):
    data = _get_eastmoney_quote(code)
    if not data:
        print(f"获取 {code} 行情失败")
        sys.exit(1)
    if output_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        sign = "+" if data["涨跌额"] >= 0 else ""
        print(f"{'='*50}")
        print(f"  {data['名称']}（{data['代码']}）")
        print(f"{'='*50}")
        print(f"  最新价：{data['最新价']}  {sign}{data['涨跌幅(%)']}%  {sign}{data['涨跌额']}")
        print(f"  今开：{data['今开']}  最高：{data['最高']}  最低：{data['最低']}  昨收：{data['昨收']}")
        print(f"  成交量：{data['成交量(手)']:,} 手  成交额：{data['成交额(亿)']} 亿  换手率：{data['换手率(%)']}%")
        print(f"  数据源：{data['数据源']}  更新：{data['更新时间']}")


def cmd_kline(code: str, freq: str, count: int, output_json: bool):
    from Ashare import get_price
    normalized = normalize_code(code)
    df = get_price(normalized, frequency=freq, count=count)
    if df is None or df.empty:
        print(f"未找到 {code} 的K线数据")
        sys.exit(1)

    df = df.reset_index()
    df.columns = ["时间", "开盘", "收盘", "最高", "最低", "成交量"]
    for col in ["开盘", "收盘", "最高", "最低"]:
        df[col] = df[col].round(2)

    if output_json:
        print(df.to_json(orient="records", force_ascii=False, date_format="iso"))
    else:
        print(f"【{code} K线数据】频率={freq} 条数={len(df)}  数据源：Ashare(腾讯/新浪)")
        print(df.to_string(index=False))


def cmd_index(output_json: bool):
    try:
        df = ak.stock_zh_index_spot_sina()
        major = ["sh000001", "sh000002", "sz399001", "sz399006", "sh000688"]
        df = df[df["代码"].isin(major)].copy()
        results = []
        for _, row in df.iterrows():
            results.append({
                "名称": row.get("名称", ""),
                "代码": row.get("代码", ""),
                "最新价": round(float(row.get("最新价", 0)), 2),
                "涨跌额": round(float(row.get("涨跌额", 0)), 2),
                "涨跌幅(%)": round(float(row.get("涨跌幅", 0)), 2),
            })
        if output_json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"【大盘指数】更新时间：{datetime.now().strftime('%H:%M:%S')}  数据源：新浪财经")
            for r in results:
                sign = "+" if r["涨跌额"] >= 0 else ""
                print(f"  {r['名称']:<8} {r['最新价']:>10.2f}  {sign}{r['涨跌幅(%)']:>6.2f}%  {sign}{r['涨跌额']:>8.2f}")
    except Exception as e:
        print(f"获取大盘指数失败：{e}")
        sys.exit(1)


def cmd_hot_sectors(top: int, output_json: bool):
    try:
        df = ak.stock_board_concept_name_em()
        df = df.sort_values(by="涨跌幅", ascending=False).head(top)
        results = []
        for i, (_, row) in enumerate(df.iterrows(), 1):
            results.append({
                "排名": i,
                "板块名称": row.get("板块名称", ""),
                "涨跌幅(%)": round(row.get("涨跌幅", 0), 2),
                "换手率(%)": round(row.get("换手率", 0), 2) if row.get("换手率") else 0,
                "总市值(亿)": round(row.get("总市值", 0) / 1e8, 2) if row.get("总市值") else 0,
            })
        if output_json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"【热点概念板块 TOP{top}】数据源：东方财富  更新：{datetime.now().strftime('%H:%M:%S')}")
            for r in results:
                sign = "+" if r["涨跌幅(%)"] >= 0 else ""
                print(f"  {r['排名']:>3}. {r['板块名称']:<14} {sign}{r['涨跌幅(%)']}%  换手率：{r['换手率(%)']}%")
    except Exception as e:
        print(f"获取热点板块失败：{e}")
        sys.exit(1)


def cmd_north_money(output_json: bool):
    try:
        df = ak.stock_hsgt_fund_flow_summary_em()
        df_north = df[df["资金方向"] == "北向"].copy()
        results = []
        for _, row in df_north.iterrows():
            results.append({
                "日期": str(row.get("交易日", "")),
                "板块": row.get("板块", ""),
                "净买额(亿)": round(float(row.get("成交净买额", 0)), 2),
                "净流入(亿)": round(float(row.get("资金净流入", 0)), 2),
                "指数涨跌(%)": round(float(row.get("指数涨跌幅", 0)), 2),
            })
        if output_json:
            print(json.dumps(results, ensure_ascii=False, indent=2))
        else:
            print(f"【北向资金】数据源：东方财富  更新：{datetime.now().strftime('%H:%M:%S')}")
            for r in results:
                sign = "+" if r["净买额(亿)"] >= 0 else ""
                print(f"  {r['日期']}  {r['板块']:<10} 净买额：{sign}{r['净买额(亿)']} 亿  净流入：{sign}{r['净流入(亿)']} 亿")
    except Exception as e:
        print(f"获取北向资金失败：{e}")
        sys.exit(1)


def cmd_lhb(start: str, end: str, top: int, output_json: bool):
    if not end:
        end = datetime.now().strftime("%Y%m%d")
    if not start:
        start = (datetime.now() - timedelta(days=3)).strftime("%Y%m%d")
    try:
        df = ak.stock_lhb_detail_em(start_date=start, end_date=end)
        if df is None or df.empty:
            print(f"未找到 {start}~{end} 的龙虎榜数据")
            return
        cols_map = {
            "代码": "代码", "名称": "名称", "上榜日": "上榜日",
            "收盘价": "收盘价", "涨跌幅": "涨跌幅(%)",
            "龙虎榜净买额": "净买额(万)", "上榜原因": "上榜原因",
        }
        available = [c for c in cols_map if c in df.columns]
        df = df[available].copy().head(top)
        df = df.rename(columns=cols_map)
        if "净买额(万)" in df.columns:
            df["净买额(万)"] = (df["净买额(万)"] / 1e4).round(2)
        if output_json:
            print(df.to_json(orient="records", force_ascii=False))
        else:
            print(f"【龙虎榜】{start}~{end}  数据源：东方财富")
            print(df.to_string(index=False))
    except Exception as e:
        print(f"获取龙虎榜失败：{e}")
        sys.exit(1)


def cmd_limit_stats(output_json: bool):
    today = datetime.now().strftime("%Y%m%d")
    try:
        df_up = ak.stock_zt_pool_em(date=today)
        up_count = len(df_up) if df_up is not None else 0
    except Exception:
        up_count = 0
    try:
        df_down = ak.stock_zt_pool_dtgc_em(date=today)
        down_count = len(df_down) if df_down is not None else 0
    except Exception:
        down_count = 0
    result = {"日期": datetime.now().strftime("%Y-%m-%d"), "涨停数量": up_count, "跌停数量": down_count}
    if output_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"【涨跌停统计】{result['日期']}  数据源：东方财富")
        print(f"  涨停：{up_count} 只  跌停：{down_count} 只")


def cmd_limit_up_pool(date: str, top: int, output_json: bool):
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    try:
        df = ak.stock_zt_pool_em(date=date)
        if df is None or df.empty:
            print(f"未找到 {date} 的涨停股数据")
            return
        keep = ["序号", "代码", "名称", "涨跌幅", "最新价", "成交额", "换手率", "封板资金", "连板数", "所属行业"]
        available = [c for c in keep if c in df.columns]
        df = df[available].head(top).copy()
        if "成交额" in df.columns:
            df["成交额(亿)"] = (df["成交额"] / 1e8).round(2)
            df = df.drop(columns=["成交额"])
        if output_json:
            print(df.to_json(orient="records", force_ascii=False))
        else:
            print(f"【涨停股池】{date}  共 {len(df)} 只  数据源：东方财富")
            print(df.to_string(index=False))
    except Exception as e:
        print(f"获取涨停股池失败：{e}")
        sys.exit(1)


def cmd_fund_flow(code: str, days: int, output_json: bool):
    normalized = normalize_code(code)
    market = "sh" if normalized.startswith("sh") else "sz"
    clean = normalized[2:]
    try:
        df = ak.stock_individual_fund_flow(stock=clean, market=market)
        if df is None or df.empty:
            print(f"未找到 {code} 的资金流向数据")
            return
        df = df.tail(days).iloc[::-1].copy()
        keep = ["日期", "收盘价", "涨跌幅", "主力净流入-净额", "主力净流入-净占比",
                "超大单净流入-净额", "大单净流入-净额", "中单净流入-净额", "小单净流入-净额"]
        available = [c for c in keep if c in df.columns]
        df = df[available].copy()
        for col in [c for c in df.columns if "净额" in c]:
            df[col] = (df[col] / 1e4).round(2)
        if output_json:
            print(df.to_json(orient="records", force_ascii=False))
        else:
            print(f"【{code} 资金流向】近 {days} 日  数据源：东方财富（单位：万元）")
            print(df.to_string(index=False))
    except Exception as e:
        print(f"获取资金流向失败：{e}")
        sys.exit(1)


def cmd_consecutive_limit(date: str, top: int, output_json: bool):
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    try:
        df = ak.stock_zt_pool_previous_em(date=date)
        if df is None or df.empty:
            print(f"未找到 {date} 的连板股数据")
            return
        keep = ["序号", "代码", "名称", "涨跌幅", "最新价", "成交额", "换手率", "昨日连板数", "所属行业"]
        available = [c for c in keep if c in df.columns]
        df = df[available].head(top).copy()
        if "成交额" in df.columns:
            df["成交额(亿)"] = (df["成交额"] / 1e8).round(2)
            df = df.drop(columns=["成交额"])
        if output_json:
            print(df.to_json(orient="records", force_ascii=False))
        else:
            print(f"【连板股】{date}  共 {len(df)} 只  数据源：东方财富")
            print(df.to_string(index=False))
    except Exception as e:
        print(f"获取连板股失败：{e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="A股实时行情数据 (akshare + ashares)")
    parser.add_argument("--quote", metavar="CODE", help="实时行情快照")
    parser.add_argument("--kline", metavar="CODE", help="实时K线")
    parser.add_argument("--freq", default="1d", help="K线频率：1m/5m/15m/30m/60m/1d/1w/1M（默认1d）")
    parser.add_argument("--count", type=int, default=60, help="K线条数（默认60）")
    parser.add_argument("--index", action="store_true", help="大盘指数")
    parser.add_argument("--hot-sectors", action="store_true", help="热点概念板块")
    parser.add_argument("--top", type=int, default=20, help="热点板块/涨停池返回数量（默认20）")
    parser.add_argument("--north-money", action="store_true", help="北向资金")
    parser.add_argument("--lhb", action="store_true", help="龙虎榜")
    parser.add_argument("--start", help="开始日期，格式YYYYMMDD")
    parser.add_argument("--end", help="结束日期，格式YYYYMMDD")
    parser.add_argument("--limit-stats", action="store_true", help="涨跌停统计")
    parser.add_argument("--limit-up-pool", action="store_true", help="涨停股池")
    parser.add_argument("--date", help="日期，格式YYYYMMDD（默认今日）")
    parser.add_argument("--fund-flow", metavar="CODE", help="个股资金流向")
    parser.add_argument("--days", type=int, default=10, help="资金流向天数（默认10）")
    parser.add_argument("--consecutive-limit", action="store_true", help="连板股")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出JSON格式")
    args = parser.parse_args()

    if args.quote:
        cmd_quote(args.quote, args.output_json)
    elif args.kline:
        cmd_kline(args.kline, args.freq, args.count, args.output_json)
    elif args.index:
        cmd_index(args.output_json)
    elif args.hot_sectors:
        cmd_hot_sectors(args.top, args.output_json)
    elif args.north_money:
        cmd_north_money(args.output_json)
    elif args.lhb:
        cmd_lhb(args.start, args.end, args.top, args.output_json)
    elif args.limit_stats:
        cmd_limit_stats(args.output_json)
    elif args.limit_up_pool:
        cmd_limit_up_pool(args.date, args.top, args.output_json)
    elif args.fund_flow:
        cmd_fund_flow(args.fund_flow, args.days, args.output_json)
    elif args.consecutive_limit:
        cmd_consecutive_limit(args.date, args.top, args.output_json)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
