#!/usr/bin/env python3
"""
A股实时行情数据脚本
数据源：东方财富 / 新浪财经（通过 akshare）+ 腾讯/新浪实时K线（直接API）

依赖安装：pip install akshare pandas requests

用法示例：
  python3 fetch_realtime.py --quote 600519
  python3 fetch_realtime.py --kline 600519 --freq 1d --count 30
  python3 fetch_realtime.py --intraday-kline 600519 --freq 5m
  python3 fetch_realtime.py --multi-quote 600519,000001,300750
  python3 fetch_realtime.py --index
  python3 fetch_realtime.py --north-money
  python3 fetch_realtime.py --lhb --start 20260310 --end 20260318
  python3 fetch_realtime.py --limit-stats
  python3 fetch_realtime.py --limit-up-pool --date 20260318
  python3 fetch_realtime.py --fund-flow 600519
  python3 fetch_realtime.py --consecutive-limit
  python3 fetch_realtime.py --market-news --news-limit 50
  python3 fetch_realtime.py --boards-summary --boards-limit 60 --boards-sort market_cap_desc
  python3 fetch_realtime.py --boards-detail --boards-group-key 半导体 --boards-items-limit 300
  python3 fetch_realtime.py --all-quote --top 20
  python3 fetch_realtime.py --all-quote --sort change_pct_desc --top 50
  python3 fetch_realtime.py --tick 600519
  python3 fetch_realtime.py --tick 600519 --tick-page 2
"""

import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, date, time as time_type
from typing import Optional

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import akshare as ak


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

SINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
TENCENT_DAY_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_MIN_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
SINA_QUOTE_URL = "https://hq.sinajs.cn/list="
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
TENCENT_TICK_URL = "https://stock.gtimg.cn/data/index.php"
MARKET_NEWS_URL = "https://dang-invest.com/api/market/news"
BOARDS_SUMMARY_URL = "https://dang-invest.com/api/market/boards/summary"
BOARDS_DETAIL_URL = "https://dang-invest.com/api/market/boards/detail"

SINA_FREQ_MAP = {
    '5m': 5, '15m': 15, '30m': 30, '60m': 60,
    '1d': 240, '1w': 1200, '1M': 7200,
}
TENCENT_DAY_FREQ_MAP = {
    '1d': 'day', '1w': 'week', '1M': 'month',
}


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.4,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _http_get_json(url: str, params: dict = None, timeout: int = 10):
    session = _build_session()
    resp = session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def normalize_code(code: str) -> str:
    code = code.strip()
    if '.XSHG' in code:
        return 'sh' + code.replace('.XSHG', '')
    if '.XSHE' in code:
        return 'sz' + code.replace('.XSHE', '')
    if '.' in code:
        parts = code.split('.')
        if len(parts) == 2:
            prefix, suffix = parts[0].lower(), parts[1]
            if prefix in ('sh', 'sz') and suffix.isdigit():
                return f"{prefix}{suffix}"
    if code.lower().startswith(('sh', 'sz')):
        return code.lower()
    if code.isdigit():
        if code.startswith('6'):
            return f"sh{code}"
        elif code.startswith(('0', '2', '3')):
            return f"sz{code}"
    return code.lower()


def _get_price_sina(code: str, count: int, frequency: str) -> pd.DataFrame:
    freq_min = SINA_FREQ_MAP.get(frequency, 240)
    params = {"symbol": code, "scale": freq_min, "ma": 5, "datalen": count}
    try:
        data = _http_get_json(SINA_KLINE_URL, params=params, timeout=10)
        if not data or isinstance(data, dict):
            return None
        df = pd.DataFrame(data, columns=['day', 'open', 'high', 'low', 'close', 'volume'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        df['day'] = pd.to_datetime(df['day'])
        df = df.set_index('day')
        df.index.name = ''
        return df
    except Exception:
        return None


def _get_price_day_tx(code: str, count: int, frequency: str) -> pd.DataFrame:
    unit = TENCENT_DAY_FREQ_MAP.get(frequency, 'day')
    end_date = ''
    url = f"{TENCENT_DAY_URL}?param={code},{unit},,{end_date},{count},qfq"
    try:
        st = _http_get_json(url, timeout=10)
        if 'data' not in st or code not in st['data']:
            return None
        stk = st['data'][code]
        ms = 'qfq' + unit
        buf = stk[ms] if ms in stk else stk.get(unit)
        if not buf:
            return None
        df = pd.DataFrame(buf, columns=['time', 'open', 'close', 'high', 'low', 'volume'], dtype='float')
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time')
        df.index.name = ''
        return df
    except Exception:
        return None


def _get_price_min_tx(code: str, count: int, frequency: str) -> pd.DataFrame:
    ts = int(frequency[:-1]) if frequency[:-1].isdigit() else 1
    url = f"{TENCENT_MIN_URL}?param={code},m{ts},,{count}"
    try:
        st = _http_get_json(url, timeout=10)
        if 'data' not in st or code not in st['data']:
            return None
        mkey = 'm' + str(ts)
        buf = st['data'][code].get(mkey)
        if not buf:
            return None
        df = pd.DataFrame(buf, columns=['time', 'open', 'close', 'high', 'low', 'volume', 'n1', 'n2'])
        df = df[['time', 'open', 'close', 'high', 'low', 'volume']]
        df[['open', 'close', 'high', 'low', 'volume']] = df[['open', 'close', 'high', 'low', 'volume']].astype(float)
        df['time'] = pd.to_datetime(df['time'])
        df = df.set_index('time')
        df.index.name = ''
        if 'qt' in st['data'][code] and code in st['data'][code].get('qt', {}):
            try:
                df['close'].iloc[-1] = float(st['data'][code]['qt'][code][3])
            except Exception:
                pass
        return df
    except Exception:
        return None


def get_price(code: str, frequency: str = '1d', count: int = 60) -> pd.DataFrame:
    """
    通过腾讯/新浪 API 获取股票K线数据，与 Ashare.get_price 行为等价。
    """
    normalized = normalize_code(code)

    if frequency in ('1d', '1w', '1M'):
        df = _get_price_sina(normalized, count, frequency)
        if df is not None and not df.empty:
            return df
        df = _get_price_day_tx(normalized, count, frequency)
        if df is not None and not df.empty:
            return df
        # 最后兜底：akshare 新浪日线（仅1d可用）
        if frequency == '1d':
            try:
                ak_df = ak.stock_zh_a_daily(symbol=normalized, adjust='')
                if ak_df is not None and not ak_df.empty:
                    ak_df = ak_df.tail(count).copy()
                    ak_df = ak_df.rename(columns={'date': 'time'})
                    ak_df['time'] = pd.to_datetime(ak_df['time'])
                    ak_df = ak_df.set_index('time')
                    ak_df.index.name = ''
                    return ak_df[['open', 'high', 'low', 'close', 'volume']]
            except Exception:
                pass
    elif frequency == '1m':
        df = _get_price_min_tx(normalized, count, frequency)
        if df is not None and not df.empty:
            return df
    else:
        df = _get_price_sina(normalized, count, frequency)
        if df is not None and not df.empty:
            return df
        df = _get_price_min_tx(normalized, count, frequency)
        if df is not None and not df.empty:
            return df

    return None


def _get_market_status() -> str:
    now = datetime.now()
    current_time = now.time()
    if now.weekday() >= 5:
        return 'closed'
    morning_start = time_type(9, 30)
    morning_end = time_type(11, 30)
    afternoon_start = time_type(13, 0)
    afternoon_end = time_type(15, 0)
    if morning_start <= current_time <= morning_end:
        return 'trading'
    elif afternoon_start <= current_time <= afternoon_end:
        return 'trading'
    elif time_type(9, 0) <= current_time < morning_start:
        return 'pre_market'
    elif current_time > afternoon_end:
        return 'post_market'
    else:
        return 'closed'


def _aggregate_intraday_data(df_min: pd.DataFrame, today: date) -> dict:
    df_today = df_min[df_min.index.date == today].copy()
    if df_today.empty:
        return None
    return {
        'open': df_today.iloc[0]['open'],
        'high': df_today['high'].max(),
        'low': df_today['low'].min(),
        'close': df_today.iloc[-1]['close'],
        'volume': df_today['volume'].sum(),
    }


def cmd_quote(code: str, output_json: bool):
    """
    实时行情快照，使用分钟K线聚合方式：
    1. 日线获取昨收
    2. 5分钟K线聚合今日 OHLCV
    3. 计算涨跌幅
    4. 附带市场状态
    """
    normalized = normalize_code(code)
    today = date.today()

    df_day = get_price(normalized, frequency='1d', count=120)
    if df_day is None or df_day.empty or len(df_day) < 2:
        print(f"获取 {code} 日线数据失败")
        sys.exit(1)

    last_date = df_day.index[-1].date()
    if last_date == today:
        prev_close = df_day.iloc[-2]['close']
    else:
        prev_close = df_day.iloc[-1]['close']

    today_data = None
    df_min = get_price(normalized, frequency='5m', count=320)
    if df_min is not None and not df_min.empty:
        today_data = _aggregate_intraday_data(df_min, today)

    if today_data is None:
        df_min15 = get_price(normalized, frequency='15m', count=320)
        if df_min15 is not None and not df_min15.empty:
            today_data = _aggregate_intraday_data(df_min15, today)

    if today_data:
        latest_price = today_data['close']
        today_open = today_data['open']
        today_high = today_data['high']
        today_low = today_data['low']
        today_volume = today_data['volume']
        display_date = today.strftime('%Y-%m-%d')
        date_label = '今日'
    else:
        latest_row = df_day.iloc[-1]
        latest_price = latest_row['close']
        today_open = latest_row['open']
        today_high = latest_row['high']
        today_low = latest_row['low']
        today_volume = latest_row['volume']
        display_date = last_date.strftime('%Y-%m-%d')
        date_label = '最近'

    change = latest_price - prev_close
    change_pct = (change / prev_close * 100) if prev_close > 0 else 0

    market_status = _get_market_status()
    status_map = {'trading': '交易中', 'closed': '休市', 'pre_market': '盘前', 'post_market': '盘后'}
    status_label = status_map.get(market_status, market_status)

    data = {
        "代码": code,
        "日期": display_date,
        "最新价": round(latest_price, 2),
        "涨跌额": round(change, 2),
        "涨跌幅(%)": round(change_pct, 2),
        "今开": round(today_open, 2),
        "最高": round(today_high, 2),
        "最低": round(today_low, 2),
        "昨收": round(prev_close, 2),
        "成交量": int(today_volume),
        "市场状态": status_label,
        "数据源": "新浪/腾讯",
        "更新时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if today_data is None:
        data["备注"] = f"非交易日或休市，显示{date_label}交易日数据"

    if output_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        sign = "+" if data["涨跌额"] >= 0 else ""
        print(f"{'='*50}")
        print(f"  {data['代码']}  {data['日期']}  [{data['市场状态']}]")
        print(f"{'='*50}")
        print(f"  最新价：{data['最新价']}  {sign}{data['涨跌幅(%)']}%  {sign}{data['涨跌额']}")
        print(f"  今开：{data['今开']}  最高：{data['最高']}  最低：{data['最低']}  昨收：{data['昨收']}")
        print(f"  成交量：{data['成交量']:,}  数据源：{data['数据源']}  更新：{data['更新时间']}")
        if "备注" in data:
            print(f"  备注：{data['备注']}")


def cmd_kline(code: str, freq: str, count: int, output_json: bool):
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
        print(f"【{code} K线数据】频率={freq} 条数={len(df)}  数据源：腾讯/新浪")
        print(df.to_string(index=False))


def cmd_intraday_kline(code: str, freq: str, output_json: bool):
    valid_freqs = ['1m', '5m', '15m', '30m', '60m']
    if freq not in valid_freqs:
        print(f"分钟K线频率无效：{freq}，支持：{valid_freqs}")
        sys.exit(1)

    normalized = normalize_code(code)
    today = date.today()

    df = get_price(normalized, frequency=freq, count=320)
    if df is None or df.empty:
        print(f"未找到 {code} 的分钟K线数据")
        sys.exit(1)

    df_today = df[df.index.date == today].copy()
    if df_today.empty:
        print(f"股票 {code} 今日（{today}）暂无分钟K线数据")
        return

    df_today = df_today.reset_index()
    df_today.columns = ["时间", "开盘", "最高", "最低", "收盘", "成交量"]
    for col in ["开盘", "最高", "最低", "收盘"]:
        df_today[col] = df_today[col].round(2)

    if output_json:
        print(df_today.to_json(orient="records", force_ascii=False, date_format="iso"))
    else:
        print(f"【{code} 今日分钟K线】频率={freq} 条数={len(df_today)}  数据源：腾讯/新浪")
        print(df_today.to_string(index=False))


def cmd_multi_quote(codes_str: str, output_json: bool):
    codes = [c.strip() for c in codes_str.split(',') if c.strip()]
    if not codes:
        print("请提供股票代码，用逗号分隔")
        sys.exit(1)
    if len(codes) > 10:
        print("批量查询最多支持10只股票")
        sys.exit(1)

    today = date.today()
    results = []

    for code in codes:
        normalized = normalize_code(code)
        try:
            df_day = get_price(normalized, frequency='1d', count=120)
            if df_day is None or df_day.empty or len(df_day) < 2:
                results.append({"代码": code, "最新价": "N/A", "涨跌幅(%)": None, "昨收": "N/A", "状态": "无数据"})
                continue

            last_date = df_day.index[-1].date()
            prev_close = df_day.iloc[-2]['close'] if last_date == today else df_day.iloc[-1]['close']

            latest_price = None
            df_min = get_price(normalized, frequency='5m', count=320)
            if df_min is not None and not df_min.empty:
                df_t = df_min[df_min.index.date == today]
                if not df_t.empty:
                    latest_price = df_t.iloc[-1]['close']

            if latest_price is None:
                latest_price = df_day.iloc[-1]['close']

            change_pct = ((latest_price - prev_close) / prev_close * 100) if prev_close > 0 else 0
            results.append({
                "代码": code,
                "最新价": round(latest_price, 2),
                "涨跌幅(%)": round(change_pct, 2),
                "昨收": round(prev_close, 2),
                "状态": "成功",
            })
        except Exception as e:
            results.append({"代码": code, "最新价": "N/A", "涨跌幅(%)": None, "昨收": "N/A", "状态": f"失败: {e}"})

    results.sort(key=lambda x: x["涨跌幅(%)"] if x["涨跌幅(%)"] is not None else float('-inf'), reverse=True)

    if output_json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"【批量行情】{datetime.now().strftime('%H:%M:%S')}  数据源：腾讯/新浪")
        df = pd.DataFrame(results)
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
            print(f"未找到 {start}~{end} 的龙虎榜数据（可能当日数据尚未发布或该日期无龙虎榜数据）")
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
        error_msg = str(e)
        if 'NoneType' in error_msg:
            print(f"未找到 {start}~{end} 的龙虎榜数据（可能当日数据尚未发布或该日期无龙虎榜数据）")
        else:
            print(f"获取龙虎榜失败：{error_msg}")
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


def cmd_limit_up_pool(date_str: str, top: int, output_json: bool):
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    try:
        df = ak.stock_zt_pool_em(date=date_str)
        if df is None or df.empty:
            print(f"未找到 {date_str} 的涨停股数据")
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
            print(f"【涨停股池】{date_str}  共 {len(df)} 只  数据源：东方财富")
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


def cmd_market_news(limit: int, offset: int, output_json: bool):
    try:
        session = _build_session()
        resp = session.get(MARKET_NEWS_URL, params={"limit": limit, "offset": offset}, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"获取市场新闻失败：{e}")
        sys.exit(1)

    items = payload.get("data") or []
    meta = {
        "url": MARKET_NEWS_URL,
        "limit": limit,
        "offset": offset,
        "count": payload.get("count"),
        "has_more": payload.get("has_more"),
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "DangInvest",
    }

    if output_json:
        print(json.dumps({"meta": meta, "data": items}, ensure_ascii=False, indent=2))
        return

    display_n = min(len(items), 20)
    print(f"【市场新闻】{meta['update_time']}  共 {len(items)} 条（limit={limit}, offset={offset}）  数据源：DangInvest")
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


def cmd_boards_summary(mode: str, limit: int, sort: str, output_json: bool):
    try:
        session = _build_session()
        resp = session.get(
            BOARDS_SUMMARY_URL,
            params={"mode": mode, "limit": limit, "sort": sort},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"获取板块概览失败：{e}")
        sys.exit(1)

    data = payload.get("data") or {}
    items = data.get("items") or []
    meta = {
        "url": BOARDS_SUMMARY_URL,
        "mode": mode,
        "limit": limit,
        "sort": sort,
        "tradeDate": payload.get("tradeDate"),
        "snapshotTsMs": payload.get("snapshotTsMs"),
        "count": data.get("count"),
        "total": data.get("total"),
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "DangInvest",
    }

    if output_json:
        print(json.dumps({"meta": meta, "data": items}, ensure_ascii=False, indent=2))
        return

    display_n = min(len(items), 20)
    print(f"【板块概览】{meta['tradeDate']}  共 {len(items)} 个（limit={limit}, sort={sort}）  数据源：DangInvest")
    for i, item in enumerate(items[:display_n]):
        item = item or {}
        label = item.get("groupLabel", "")
        changePct = item.get("changePct")
        count = item.get("count", 0)
        mc_yi = round(float(item.get("totalMarketCapYuan") or 0) / 1e8, 2)
        to_yi = round(float(item.get("totalTurnoverYuan") or 0) / 1e8, 2)
        if changePct is None:
            change_str = "N/A"
            sign = ""
        else:
            sign = "+" if float(changePct) >= 0 else ""
            change_str = f"{round(float(changePct), 2)}%"
        print(f"  {i + 1:>3}. {label:<14} {sign}{change_str:<8} 数量={count:<4} 市值(亿)={mc_yi} 成交(亿)={to_yi}")
    if len(items) > display_n:
        print(f"  ... 已截断显示前 {display_n} 个（共 {len(items)} 个）")


def cmd_boards_detail(mode: str, group_key: str, sort: str, items_limit: int, items_offset: int, output_json: bool):
    if not group_key:
        print("--boards-group-key 不能为空")
        sys.exit(1)

    try:
        session = _build_session()
        resp = session.get(
            BOARDS_DETAIL_URL,
            params={"mode": mode, "groupKey": group_key, "sort": sort, "items_limit": items_limit, "items_offset": items_offset},
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        print(f"获取板块成分失败：{e}")
        sys.exit(1)

    meta = {
        "url": BOARDS_DETAIL_URL,
        "mode": mode,
        "groupKey": group_key,
        "sort": sort,
        "items_limit": items_limit,
        "items_offset": items_offset,
        "tradeDate": payload.get("tradeDate"),
        "snapshotTsMs": payload.get("snapshotTsMs"),
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
    changePct = summary.get("changePct")
    if changePct is None:
        change_str, sign = "N/A", ""
    else:
        sign = "+" if float(changePct) >= 0 else ""
        change_str = f"{round(float(changePct), 2)}%"
    print(f"【板块成分】{meta['tradeDate']}  {group_label}  数量={trade_count} 市值(亿)={mc_yi} 成交(亿)={to_yi} 涨跌幅={sign}{change_str}  数据源：DangInvest")

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
        print(f"  {i + 1:>3}. {code:<10} {name:<12} 现价={price_str:<8} {sign_i}{cp_str:<8} 成交(亿)={to_yi_i} 市值(亿)={mc_yi_i}")
    if len(items) > display_n:
        print(f"  ... 已截断显示前 {display_n} 只（共 {len(items)} 只）")


# ---------------------------------------------------------------------------
# 全市场实时行情
# ---------------------------------------------------------------------------

_ALL_STOCK_CODES = None


def _generate_all_codes() -> list:
    """生成沪深全市场候选代码列表"""
    global _ALL_STOCK_CODES
    if _ALL_STOCK_CODES is not None:
        return _ALL_STOCK_CODES
    codes = []
    for i in range(600000, 606000):
        codes.append(f"sh{i}")
    for i in range(688000, 690000):
        codes.append(f"sh{i}")
    for i in range(1, 5000):
        codes.append(f"sz{i:06d}")
    for i in range(300000, 302000):
        codes.append(f"sz{i}")
    _ALL_STOCK_CODES = codes
    return codes


def _parse_tencent_quote(line: str) -> Optional[dict]:
    """解析腾讯 qt.gtimg.cn 单行数据，返回结构化 dict"""
    if '~' not in line or len(line) < 50:
        return None
    parts = line.split('~')
    if len(parts) < 48:
        return None
    try:
        price = float(parts[3]) if parts[3] else 0
        if price <= 0:
            return None
        prev_close = float(parts[4]) if parts[4] else 0
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
        market_prefix = "sh" if parts[0] == "1" else "sz"
        return {
            "code": f"{market_prefix}{parts[2]}",
            "name": parts[1],
            "price": price,
            "prev_close": prev_close,
            "open": float(parts[5]) if parts[5] else 0,
            "change_pct": change_pct,
            "volume": int(parts[6]) if parts[6] else 0,
            "amount": float(parts[37]) * 10000 if parts[37] else 0,
            "turnover_rate": float(parts[38]) if parts[38] else 0,
            "pe": float(parts[39]) if parts[39] else 0,
            "high": float(parts[33]) if parts[33] else 0,
            "low": float(parts[34]) if parts[34] else 0,
            "amplitude": float(parts[43]) if parts[43] else 0,
            "market_cap": float(parts[45]) if parts[45] else 0,
            "pb": float(parts[46]) if parts[46] else 0,
            "limit_up": float(parts[47]) if parts[47] else 0,
            "limit_down": float(parts[48]) if len(parts) > 48 and parts[48] else 0,
        }
    except (ValueError, IndexError):
        return None


def _parse_sina_quote(line: str) -> Optional[dict]:
    """解析新浪 hq.sinajs.cn 单行数据作为降级备源"""
    if '="' not in line:
        return None
    code_part = line.split('="')[0].replace("var hq_str_", "")
    val = line.split('="')[1].rstrip('";')
    if not val:
        return None
    fields = val.split(',')
    if len(fields) < 32:
        return None
    try:
        price = float(fields[3])
        prev_close = float(fields[2])
        if price <= 0:
            return None
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
        return {
            "code": code_part,
            "name": fields[0],
            "price": price,
            "prev_close": prev_close,
            "open": float(fields[1]),
            "change_pct": change_pct,
            "volume": int(float(fields[8])),
            "amount": float(fields[9]),
            "high": float(fields[4]),
            "low": float(fields[5]),
        }
    except (ValueError, IndexError):
        return None


_ALL_QUOTE_SORT_KEYS = {
    "change_pct_desc": ("change_pct", True),
    "change_pct_asc": ("change_pct", False),
    "amount_desc": ("amount", True),
    "turnover_rate_desc": ("turnover_rate", True),
    "market_cap_desc": ("market_cap", True),
    "market_cap_asc": ("market_cap", False),
}

BATCH_SIZE = 500
WORKERS = 4


def _fetch_all_quotes_tencent() -> list:
    """腾讯接口批量拉取全市场行情"""
    codes = _generate_all_codes()
    batches = [codes[i:i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
    session = _build_session()
    session.trust_env = False

    def fetch_batch(batch):
        resp = session.get(f"{TENCENT_QUOTE_URL}{','.join(batch)}", timeout=30)
        results = []
        for line in resp.text.strip().split('\n'):
            parsed = _parse_tencent_quote(line)
            if parsed:
                results.append(parsed)
        return results

    all_items = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(fetch_batch, b) for b in batches]
        for f in as_completed(futures):
            all_items.extend(f.result())
    return all_items


def _fetch_all_quotes_sina() -> list:
    """新浪接口批量拉取全市场行情（降级备源）"""
    codes = _generate_all_codes()
    batches = [codes[i:i + BATCH_SIZE] for i in range(0, len(codes), BATCH_SIZE)]
    session = _build_session()
    session.trust_env = False
    session.headers["Referer"] = "https://finance.sina.com.cn/"

    def fetch_batch(batch):
        resp = session.get(f"{SINA_QUOTE_URL}{','.join(batch)}", timeout=30)
        results = []
        for line in resp.text.strip().split('\n'):
            parsed = _parse_sina_quote(line)
            if parsed:
                results.append(parsed)
        return results

    all_items = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = [pool.submit(fetch_batch, b) for b in batches]
        for f in as_completed(futures):
            all_items.extend(f.result())
    return all_items


def cmd_all_quote(sort_key: str, top: int, output_json: bool):
    try:
        items = _fetch_all_quotes_tencent()
        source = "腾讯"
    except Exception:
        try:
            items = _fetch_all_quotes_sina()
            source = "新浪"
        except Exception as e:
            print(f"获取全市场行情失败：{e}")
            sys.exit(1)

    if not items:
        print("未获取到有效行情数据")
        sys.exit(1)

    sort_field, sort_reverse = _ALL_QUOTE_SORT_KEYS.get(sort_key, ("change_pct", True))
    items.sort(key=lambda x: x.get(sort_field) or 0, reverse=sort_reverse)

    meta = {
        "total": len(items),
        "sort": sort_key,
        "top": top,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": source,
    }

    display = items[:top] if top > 0 else items

    if output_json:
        print(json.dumps({"meta": meta, "data": display}, ensure_ascii=False, indent=2))
        return

    print(f"【全市场行情】{meta['update_time']}  共 {len(items)} 只  排序={sort_key}  数据源：{source}")
    for i, r in enumerate(display):
        sign = "+" if r["change_pct"] >= 0 else ""
        amt_yi = round(r.get("amount", 0) / 1e8, 2)
        tr = r.get("turnover_rate", 0)
        mc = round(r.get("market_cap", 0), 1)
        print(f"  {i + 1:>4}. {r['code']:<10} {r['name']:<8} "
              f"价={r['price']:<9} {sign}{r['change_pct']:.2f}%  "
              f"额={amt_yi}亿  换手={tr}%  市值={mc}亿")


# ---------------------------------------------------------------------------
# 个股实时成交明细
# ---------------------------------------------------------------------------

def cmd_tick(code: str, page: int, top: int, output_json: bool):
    normalized = normalize_code(code)
    session = _build_session()
    session.trust_env = False
    try:
        resp = session.get(TENCENT_TICK_URL,
                           params={"appn": "detail", "action": "data", "c": normalized, "p": page},
                           timeout=15)
        resp.raise_for_status()
        text = resp.text.strip()
    except Exception as e:
        print(f"获取成交明细失败：{e}")
        sys.exit(1)

    # 解析: v_detail_data_xxx=[总页数,"序号/时间/价格/涨跌/量(手)/额/方向|..."]
    if '=[' not in text:
        print(f"返回数据格式异常：{text[:200]}")
        sys.exit(1)

    bracket_content = text.split('=[')[1].rstrip('];')
    parts = bracket_content.split(',', 1)
    total_pages = int(parts[0]) if parts[0].strip().isdigit() else 0
    records_raw = parts[1].strip('"').split('|') if len(parts) > 1 else []

    BS_MAP = {"B": "买", "S": "卖", "M": "中"}
    records = []
    for rec in records_raw:
        fields = rec.split('/')
        if len(fields) < 7:
            continue
        records.append({
            "seq": int(fields[0]) if fields[0].isdigit() else 0,
            "time": fields[1],
            "price": float(fields[2]),
            "change": float(fields[3]),
            "volume": int(fields[4]),
            "amount": float(fields[5]),
            "direction": BS_MAP.get(fields[6], fields[6]),
        })

    meta = {
        "code": normalized,
        "page": page,
        "total_pages": total_pages,
        "records": len(records),
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "腾讯",
    }

    display = records[:top] if top > 0 else records

    if output_json:
        print(json.dumps({"meta": meta, "data": display}, ensure_ascii=False, indent=2))
        return

    print(f"【成交明细】{normalized}  第{page}页/共{total_pages}页  {len(records)}条  数据源：腾讯")
    for r in display:
        sign = "+" if r["change"] >= 0 else ""
        amt_w = round(r["amount"] / 10000, 1)
        print(f"  {r['time']}  价={r['price']:<9} {sign}{r['change']:<7} "
              f"量={r['volume']}手  额={amt_w}万  {r['direction']}")


def cmd_consecutive_limit(date_str: str, top: int, output_json: bool):
    if not date_str:
        date_str = datetime.now().strftime("%Y%m%d")
    try:
        df = ak.stock_zt_pool_previous_em(date=date_str)
        if df is None or df.empty:
            print(f"未找到 {date_str} 的连板股数据")
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
            print(f"【连板股】{date_str}  共 {len(df)} 只  数据源：东方财富")
            print(df.to_string(index=False))
    except Exception as e:
        print(f"获取连板股失败：{e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="A股实时行情数据 (akshare + 腾讯/新浪直接API)")
    parser.add_argument("--quote", metavar="CODE", help="实时行情快照（分钟K线聚合，含市场状态）")
    parser.add_argument("--kline", metavar="CODE", help="K线数据")
    parser.add_argument("--freq", default="1d", help="K线频率：1m/5m/15m/30m/60m/1d/1w/1M（默认1d）")
    parser.add_argument("--count", type=int, default=60, help="K线条数（默认60）")
    parser.add_argument("--intraday-kline", metavar="CODE", help="今日分钟K线（需配合 --freq 指定分钟级别）")
    parser.add_argument("--multi-quote", metavar="CODES", help="批量实时行情，逗号分隔，最多10只")
    parser.add_argument("--index", action="store_true", help="大盘指数")
    parser.add_argument("--top", type=int, default=20, help="返回数量（默认20）")
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
    parser.add_argument("--market-news", action="store_true", help="市场新闻（DangInvest）")
    parser.add_argument("--news-limit", type=int, default=300, help="新闻条数（默认300）")
    parser.add_argument("--news-offset", type=int, default=0, help="新闻偏移（默认0）")
    parser.add_argument("--boards-summary", action="store_true", help="行业板块概览（DangInvest）")
    parser.add_argument("--boards-detail", action="store_true", help="行业板块成分明细（DangInvest）")
    parser.add_argument("--boards-mode", default="industry", help="板块模式（默认industry）")
    parser.add_argument("--boards-limit", type=int, default=60, help="板块概览返回条数（默认60）")
    parser.add_argument("--boards-sort", default="market_cap_desc", help="板块排序（默认market_cap_desc）")
    parser.add_argument("--boards-group-key", default="", help="板块key，--boards-detail 必填（例如 半导体）")
    parser.add_argument("--boards-items-limit", type=int, default=300, help="成分返回条数（默认300）")
    parser.add_argument("--boards-items-offset", type=int, default=0, help="成分偏移（默认0）")
    parser.add_argument("--all-quote", action="store_true", help="全市场实时行情（腾讯主源/新浪备源）")
    parser.add_argument("--sort", default="change_pct_desc",
                        help="全市场排序：change_pct_desc|change_pct_asc|amount_desc|turnover_rate_desc|market_cap_desc|market_cap_asc")
    parser.add_argument("--tick", metavar="CODE", help="个股实时成交明细（腾讯）")
    parser.add_argument("--tick-page", type=int, default=0, help="成交明细页码（默认0=最新）")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出JSON格式")
    args = parser.parse_args()

    if args.quote:
        cmd_quote(args.quote, args.output_json)
    elif args.kline:
        cmd_kline(args.kline, args.freq, args.count, args.output_json)
    elif args.intraday_kline:
        freq = args.freq if args.freq in ['1m', '5m', '15m', '30m', '60m'] else '5m'
        cmd_intraday_kline(args.intraday_kline, freq, args.output_json)
    elif args.multi_quote:
        cmd_multi_quote(args.multi_quote, args.output_json)
    elif args.index:
        cmd_index(args.output_json)
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
    elif args.market_news:
        cmd_market_news(args.news_limit, args.news_offset, args.output_json)
    elif args.boards_summary:
        cmd_boards_summary(args.boards_mode, args.boards_limit, args.boards_sort, args.output_json)
    elif args.boards_detail:
        cmd_boards_detail(args.boards_mode, args.boards_group_key, args.boards_sort, args.boards_items_limit, args.boards_items_offset, args.output_json)
    elif args.all_quote:
        cmd_all_quote(args.sort, args.top, args.output_json)
    elif args.tick:
        cmd_tick(args.tick, args.tick_page, args.top, args.output_json)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
