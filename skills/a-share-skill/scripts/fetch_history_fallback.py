#!/usr/bin/env python3
"""
A股历史/基础信息兜底脚本（不依赖 Baostock）

数据源优先级：
1) K线：腾讯 -> 新浪 -> 雪球 -> 东财(akshare)
2) 基本信息：新浪 -> 腾讯
3) 行业/板块：东方财富（公司概况 + 板块成分扫描）
4) 全市场股票列表：新浪 ✅
5) 交易日历：akshare(sina) ✅
6) 指数成分：akshare(中证指数)
7) 分红配送：akshare
8) 业绩预告/快报：akshare
9) 财务指标：akshare
10) 宏观数据：akshare

完全平替 fetch_history.py 的 Baostock 能力
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ============ 数据源 URL ============
SINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
TENCENT_DAY_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={code}"
SINA_QUOTE_URL = "https://hq.sinajs.cn/list={code}"
EM_QUOTE_URL = "https://push2.eastmoney.com/api/qt/stock/get"

# 东方财富公司概况/板块接口
EM_COMPANY_URL = "https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax"
EM_BOARD_CONCEPT_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_BOARD_INDUSTRY_URL = "https://push2.eastmoney.com/api/qt/clist/get"

# 新浪全市场股票
SINA_STOCK_LIST_COUNT = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount"
SINA_STOCK_LIST_DATA = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"

SINA_FREQ_MAP = {
    "1d": 240,
    "1w": 1200,
    "1M": 7200,
}
TENCENT_DAY_FREQ_MAP = {
    "1d": "day",
    "1w": "week",
    "1M": "month",
}

# 指数代码映射
INDEX_CODE_MAP = {
    "hs300": "000300",  # 沪深300
    "sz50": "000016",   # 上证50
    "zz500": "000905",  # 中证500
}


def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://finance.eastmoney.com",
        }
    )
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def normalize_code(code: str) -> str:
    c = code.strip()
    if ".XSHG" in c:
        return "sh" + c.replace(".XSHG", "")
    if ".XSHE" in c:
        return "sz" + c.replace(".XSHE", "")
    if "." in c:
        p = c.split(".")
        if len(p) == 2:
            left = p[0].lower()
            right = p[1]
            if left in ("sh", "sz") and right.isdigit():
                return f"{left}{right}"
    c = c.lower()
    if c.startswith(("sh", "sz")):
        return c
    if c.isdigit():
        if c.startswith("6"):
            return "sh" + c
        return "sz" + c
    return c


def _code_digits(code: str) -> str:
    n = normalize_code(code)
    return n[2:] if n.startswith(("sh", "sz")) else n


def _to_secid(norm_code: str) -> str:
    digits = _code_digits(norm_code)
    if norm_code.startswith("sh"):
        return f"1.{digits}"
    return f"0.{digits}"


def _get_json(session: requests.Session, url: str, params=None, timeout: int = 10):
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _get_text(session: requests.Session, url: str, params=None, timeout: int = 10) -> str:
    r = session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.text


# ============ K线 ============
def get_kline_sina(session: requests.Session, norm_code: str, freq: str, count: int) -> pd.DataFrame:
    if freq not in SINA_FREQ_MAP:
        return pd.DataFrame()
    params = {
        "symbol": norm_code,
        "scale": SINA_FREQ_MAP[freq],
        "ma": 5,
        "datalen": count,
    }
    try:
        data = _get_json(session, SINA_KLINE_URL, params=params, timeout=10)
        if not data or isinstance(data, dict):
            return pd.DataFrame()
        df = pd.DataFrame(data)
        # 新浪返回列名为 day，统一重命名为 time
        if "day" in df.columns:
            df = df.rename(columns={"day": "time"})
        df = df[["time", "open", "high", "low", "close", "volume"]]
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"])
        return df
    except Exception:
        return pd.DataFrame()


def get_kline_tencent(session: requests.Session, norm_code: str, freq: str, count: int) -> pd.DataFrame:
    if freq not in TENCENT_DAY_FREQ_MAP:
        return pd.DataFrame()
    unit = TENCENT_DAY_FREQ_MAP[freq]
    url = f"{TENCENT_DAY_URL}?param={norm_code},{unit},,,{count},qfq"
    try:
        payload = _get_json(session, url, timeout=10)
        if "data" not in payload or norm_code not in payload["data"]:
            return pd.DataFrame()
        block = payload["data"][norm_code]
        key = "qfq" + unit
        arr = block.get(key) or block.get(unit) or []
        if not arr:
            return pd.DataFrame()
        df = pd.DataFrame(arr, columns=["time", "open", "close", "high", "low", "volume"])
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"])
        return df
    except Exception:
        return pd.DataFrame()


def _estimate_fetch_count(start: str, end: str, freq: str, default_count: int) -> int:
    """根据日期范围估算需要拉取的K线条数（含余量）。

    新浪/腾讯接口返回的是"从今天往前推 N 条"的数据，
    因此要覆盖到 start，需要拉取 今天→start 之间的交易日数量。
    """
    if not start:
        return default_count
    try:
        s = pd.to_datetime(start)
        now = pd.Timestamp.now()
        days_from_now = (now - s).days + 1
        if freq == "1d":
            # 一年约 250 个交易日，按自然日 * 0.72 + 余量
            return max(default_count, int(days_from_now * 0.72) + 30)
        if freq == "1w":
            return max(default_count, days_from_now // 7 + 10)
        if freq == "1M":
            return max(default_count, days_from_now // 30 + 5)
    except Exception:
        pass
    return default_count


def get_kline_xueqiu(session: requests.Session, norm_code: str, freq: str, count: int) -> pd.DataFrame:
    """雪球K线兜底（可能受反爬策略影响）。"""
    period_map = {"1d": "day", "1w": "week", "1M": "month"}
    if freq not in period_map:
        return pd.DataFrame()

    digits = _code_digits(norm_code)
    if len(digits) != 6:
        return pd.DataFrame()
    symbol = ("SH" if norm_code.startswith("sh") else "SZ") + digits

    url = "https://stock.xueqiu.com/v5/stock/chart/kline.json"
    params = {
        "symbol": symbol,
        "begin": int(pd.Timestamp.now().timestamp() * 1000),
        "period": period_map[freq],
        "type": "before",
        "count": max(60, int(count)),
        "indicator": "kline",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": f"https://xueqiu.com/S/{symbol}",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        r = session.get(url, params=params, headers=headers, timeout=10)
        if r.status_code != 200:
            return pd.DataFrame()
        j = r.json()
        data = (j or {}).get("data", {})
        items = data.get("item") or []
        cols = data.get("column") or []
        if not items or not cols:
            return pd.DataFrame()
        if not all(k in cols for k in ["timestamp", "open", "high", "low", "close", "volume"]):
            return pd.DataFrame()
        df = pd.DataFrame(items, columns=cols)
        out = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
        out = out.rename(columns={"timestamp": "time"})
        out["time"] = pd.to_datetime(out["time"], unit="ms", errors="coerce")
        for col in ["open", "high", "low", "close", "volume"]:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out = out.dropna(subset=["time"])
        return out
    except Exception:
        return pd.DataFrame()


def get_kline_eastmoney(norm_code: str, freq: str, start: str = None, end: str = None) -> pd.DataFrame:
    """东方财富日/周/月K线（akshare）兜底。"""
    try:
        import akshare as ak
    except Exception:
        return pd.DataFrame()

    period_map = {"1d": "daily", "1w": "weekly", "1M": "monthly"}
    if freq not in period_map:
        return pd.DataFrame()

    symbol = _code_digits(norm_code)
    if not symbol or len(symbol) != 6:
        return pd.DataFrame()

    def _fmt(d):
        if not d:
            return ""
        try:
            return pd.to_datetime(d).strftime("%Y%m%d")
        except Exception:
            return ""

    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period=period_map[freq],
            start_date=_fmt(start),
            end_date=_fmt(end),
            adjust="qfq",
        )
        if df is None or df.empty:
            return pd.DataFrame()
        # 兼容中文列
        col_map = {
            "日期": "time",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        if not set(col_map.keys()).issubset(set(df.columns)):
            return pd.DataFrame()
        out = df.rename(columns=col_map)[list(col_map.values())].copy()
        for col in ["open", "high", "low", "close", "volume"]:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out["time"] = pd.to_datetime(out["time"], errors="coerce")
        out = out.dropna(subset=["time"])
        return out
    except Exception:
        return pd.DataFrame()


def _fetch_kline_with_fallback(session: requests.Session, norm: str, freq: str, fetch_count: int, start: str = None, end: str = None, retry: int = 2):
    """历史K线主链路：腾讯优先 -> 新浪 -> 雪球 -> 东方财富(akshare)。含重试。"""
    last_df = pd.DataFrame()
    for _ in range(max(1, retry)):
        df = get_kline_tencent(session, norm, freq, fetch_count)
        if not df.empty:
            return df, "腾讯"
        last_df = df

        df = get_kline_sina(session, norm, freq, fetch_count)
        if not df.empty:
            return df, "新浪"
        last_df = df

        df = get_kline_xueqiu(session, norm, freq, fetch_count)
        if not df.empty:
            return df, "雪球"
        last_df = df

    # 最后兜底东方财富
    df = get_kline_eastmoney(norm, freq, start=start, end=end)
    if not df.empty:
        return df, "东财"

    return last_df, None


def _format_kline_output(df: pd.DataFrame, norm: str, count: int, start: str = None, end: str = None) -> pd.DataFrame:
    start_dt = pd.to_datetime(start) if start else None
    end_dt = pd.to_datetime(end) if end else None
    if start_dt is not None:
        df = df[df["time"] >= start_dt]
    if end_dt is not None:
        df = df[df["time"] <= end_dt]
    df = df.sort_values("time").tail(count)
    if df.empty:
        return pd.DataFrame()

    out = df.copy()
    out["code"] = norm
    out["preclose"] = out["close"].shift(1)
    out["pctChg"] = (out["close"] / out["preclose"] - 1) * 100
    out["time"] = out["time"].dt.strftime("%Y-%m-%d")
    cols = ["time", "code", "open", "high", "low", "close", "preclose", "volume", "pctChg"]
    return out[cols]


def cmd_kline(args):
    session = _build_session()
    norm = normalize_code(args.kline)
    fetch_count = _estimate_fetch_count(args.start, args.end, args.freq, args.count)

    df, source = _fetch_kline_with_fallback(
        session, norm, args.freq, fetch_count, start=args.start, end=args.end, retry=2
    )
    if df.empty:
        print(f"未获取到 {norm} 的K线数据（腾讯/新浪/东财均失败）")
        return

    out = _format_kline_output(df, norm, args.count, args.start, args.end)
    if out.empty:
        print(f"未找到 {norm} 在指定区间内的K线数据")
        return

    if args.output_json:
        print(out.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{norm} 历史K线】频率={args.freq} 共{len(out)}条 数据源：{source}")
        print(out.to_string(index=False))


def cmd_kline_batch(args):
    """批量历史K线：支持多代码并发拉取（默认8线程）。"""
    codes = [normalize_code(x) for x in re.split(r"[,\s]+", (args.kline_batch or "").strip()) if x]
    # 去重且保序
    uniq = []
    seen = set()
    for c in codes:
        if c and c not in seen:
            seen.add(c)
            uniq.append(c)

    if not uniq:
        print("请通过 --kline-batch 传入至少一个股票代码（逗号分隔）")
        return

    fetch_count = _estimate_fetch_count(args.start, args.end, args.freq, args.count)

    def _one(code):
        session = _build_session()
        df, source = _fetch_kline_with_fallback(
            session, code, args.freq, fetch_count, start=args.start, end=args.end, retry=max(1, int(args.retries or 2))
        )
        if df.empty:
            return {
                "code": code,
                "ok": False,
                "source": None,
                "rows": 0,
                "data": [],
                "error": "腾讯/新浪/东财均失败",
            }
        out = _format_kline_output(df, code, args.count, args.start, args.end)
        if out.empty:
            return {
                "code": code,
                "ok": False,
                "source": source,
                "rows": 0,
                "data": [],
                "error": "指定区间无数据",
            }
        return {
            "code": code,
            "ok": True,
            "source": source,
            "rows": len(out),
            "data": json.loads(out.to_json(orient="records", force_ascii=False)),
            "error": None,
        }

    results = []
    max_workers = max(1, int(args.workers or 8))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_one, c) for c in uniq]
        for f in as_completed(futs):
            results.append(f.result())

    # 二次补拉：对失败代码使用低并发再试一轮，提升100只批量成功率
    fail_codes = [r["code"] for r in results if not r.get("ok")]
    retry_pass_results = []
    if fail_codes:
        retry_workers = min(3, max_workers)
        with ThreadPoolExecutor(max_workers=retry_workers) as ex:
            futs = [ex.submit(_one, c) for c in fail_codes]
            for f in as_completed(futs):
                retry_pass_results.append(f.result())
        retry_map = {r["code"]: r for r in retry_pass_results if r.get("ok")}
        if retry_map:
            for i, r in enumerate(results):
                c = r.get("code")
                if c in retry_map:
                    results[i] = retry_map[c]

    # 按输入顺序回排
    order = {c: i for i, c in enumerate(uniq)}
    results.sort(key=lambda x: order.get(x["code"], 10**9))

    success = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]

    if args.output_json:
        print(json.dumps({
            "meta": {
                "requested": len(uniq),
                "success": len(success),
                "fail": len(fail),
                "workers": max_workers,
                "retries": int(args.retries or 2),
                "second_pass_retry": True,
                "freq": args.freq,
                "count": args.count,
                "start": args.start,
                "end": args.end,
            },
            "results": results,
        }, ensure_ascii=False))
    else:
        print(f"【批量历史K线】请求{len(uniq)}只 成功{len(success)} 失败{len(fail)} 并发={max_workers}")
        for r in success[:20]:
            print(f"  ✓ {r['code']} rows={r['rows']} source={r['source']}")
        for r in fail[:20]:
            print(f"  ✗ {r['code']} error={r['error']}")


# ============ 基本信息 ============
def _basic_from_sina(session: requests.Session, norm: str):
    url = SINA_QUOTE_URL.format(code=norm)
    try:
        text = session.get(url, timeout=8).text
        if '="' not in text or '";' not in text:
            return None
        body = text.split('="', 1)[1].rsplit('";', 1)[0]
        parts = body.split(",")
        if len(parts) < 10 or not parts[0]:
            return None
        return {
            "code": norm,
            "name": parts[0],
            "open": parts[1],
            "preclose": parts[2],
            "price": parts[3],
            "high": parts[4],
            "low": parts[5],
            "volume": parts[8],
            "amount": parts[9],
            "source": "新浪",
        }
    except Exception:
        return None


def _basic_from_tencent(session: requests.Session, norm: str):
    url = TENCENT_QUOTE_URL.format(code=norm)
    try:
        text = session.get(url, timeout=8).text
        if "~" not in text:
            return None
        body = text.split('"', 1)[1].rsplit('"', 1)[0]
        arr = body.split("~")
        if len(arr) < 38:
            return None
        return {
            "code": norm,
            "name": arr[1],
            "open": arr[5],
            "preclose": arr[4],
            "price": arr[3],
            "high": arr[33] if len(arr) > 33 else None,
            "low": arr[34] if len(arr) > 34 else None,
            "volume": arr[36] if len(arr) > 36 else None,
            "amount": arr[37] if len(arr) > 37 else None,
            "source": "腾讯",
        }
    except Exception:
        return None


def cmd_basic(args):
    session = _build_session()
    norm = normalize_code(args.basic)
    data = _basic_from_sina(session, norm) or _basic_from_tencent(session, norm)
    if not data:
        print(f"未获取到 {norm} 基本信息（新浪/腾讯均失败）")
        return
    if args.output_json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        print(f"【{norm} 基本信息】数据源：{data['source']}")
        for k in ["code", "name", "price", "open", "high", "low", "preclose", "volume", "amount"]:
            print(f"  {k}: {data.get(k)}")


# ============ 行业信息 ============
def _industry_from_eastmoney(session: requests.Session, norm: str):
    params = {
        "secid": _to_secid(norm),
        "fields": "f58,f84,f85,f127,f128,f116",
    }
    try:
        payload = _get_json(session, EM_QUOTE_URL, params=params, timeout=10)
        data = payload.get("data") or {}
        if not data:
            return None
        return {
            "code": norm,
            "name": data.get("f58"),
            "industry": data.get("f127"),
            "industry_code": data.get("f128"),
            "market_value": data.get("f116"),
            "source": "东方财富",
        }
    except Exception:
        return None


def _get_boards_from_akshare(norm: str) -> list:
    """通过 akshare 获取个股所属板块"""
    digits = _code_digits(norm)
    boards = []
    try:
        import akshare as ak
        # 使用个股信息接口获取行业
        info = ak.stock_individual_info_em(symbol=digits)
        if info is not None and not info.empty:
            # 提取行业信息
            industry_row = info[info['item'] == '行业']
            if not industry_row.empty:
                industry = industry_row['value'].values[0]
                boards.append({"group_key": "industry", "group_label": industry})
    except Exception:
        pass
    return boards


def _scan_boards_for_code(session: requests.Session, norm: str, max_boards: int = 80):
    """扫描板块归属（东方财富接口）- 已弃用，改用 akshare"""
    return _get_boards_from_akshare(norm)


def cmd_industry(args):
    session = _build_session()
    norm = normalize_code(args.industry)
    
    # 先从公司概况获取行业信息
    industry_info = None
    try:
        r = session.get(EM_COMPANY_URL, params={"code": norm}, timeout=10)
        payload = r.json()
        if payload.get("jbzl"):
            jbzl = payload["jbzl"]
            industry_info = {
                "code": norm,
                "name": jbzl.get("agjc"),
                "industry": jbzl.get("sshy"),
                "industry_zjh": jbzl.get("sszjhhy"),  # 证监会行业
                "source": "东方财富",
            }
    except Exception:
        pass
    
    # 如果公司概况失败，再用quote接口
    if not industry_info:
        industry_info = _industry_from_eastmoney(session, norm)
    
    boards = _scan_boards_for_code(session, norm, max_boards=args.board_scan_limit) if args.with_boards else []

    output = {
        "code": norm,
        "industry_info": industry_info,
        "boards": boards,
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if args.output_json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return

    print(f"【{norm} 行业/板块】")
    if industry_info:
        print(f"  行业: {industry_info.get('industry') or 'N/A'}")
        if industry_info.get('industry_zjh'):
            print(f"  证监会行业: {industry_info.get('industry_zjh')}")
        print("  行业来源: 东方财富")
    else:
        print("  行业: N/A（东方财富接口未返回）")
    if boards:
        print(f"  板块命中: {len(boards)} 个（东方财富）")
        for b in boards[:20]:
            print(f"    - {b.get('group_label')}")
    elif args.with_boards:
        print("  板块命中: 0（或板块接口暂不可用）")


# ============ 全市场股票列表 ============
def _normalize_list_code(code: str) -> str:
    c = str(code or "").strip().upper().replace(".", "")
    if not c:
        return ""
    if c.startswith(("SH", "SZ")) and len(c) >= 8:
        return c[:2].lower() + c[2:]
    if c.isdigit():
        return ("sh" if c.startswith("6") else "sz") + c
    return c.lower()


def _match_market(code: str, market: str) -> bool:
    if not code:
        return False
    if market == "sh":
        return code.startswith("sh")
    if market == "sz":
        return code.startswith("sz")
    return code.startswith(("sh", "sz"))


def _fetch_all_stocks_sina(session: requests.Session, market: str) -> pd.DataFrame:
    node_map = {None: "hs_a", "sh": "sh_a", "sz": "sz_a"}
    node = node_map.get(market, "hs_a")
    try:
        r = session.get(SINA_STOCK_LIST_COUNT, params={"node": node}, timeout=30)
        total = int(r.text.strip('"'))
    except Exception:
        total = 5000

    rows = []
    page_size = 100
    total_pages = (total + page_size - 1) // page_size
    for page in range(1, total_pages + 1):
        params = {
            "page": page,
            "num": page_size,
            "sort": "symbol",
            "asc": 1,
            "node": node,
            "symbol": "",
            "_s_r_a": "page",
        }
        r = session.get(SINA_STOCK_LIST_DATA, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data:
            break
        for item in data:
            code = _normalize_list_code(item.get("symbol", ""))
            name = str(item.get("name", "")).strip()
            if not _match_market(code, market):
                continue
            if code and name and not code.startswith("bj"):
                rows.append({"代码": code, "名称": name, "来源": "新浪"})
    return pd.DataFrame(rows)


def _fetch_all_stocks_tencent(market: str) -> pd.DataFrame:
    import akshare as ak

    df = ak.stock_zh_a_spot()
    if df is None or df.empty or "代码" not in df.columns or "名称" not in df.columns:
        return pd.DataFrame()
    out = df[["代码", "名称"]].copy()
    out["代码"] = out["代码"].map(_normalize_list_code)
    out["名称"] = out["名称"].astype(str).str.strip()
    out = out[out["代码"].map(lambda x: _match_market(x, market))]
    out = out[out["名称"] != ""]
    out["来源"] = "腾讯"
    return out


def _fetch_all_stocks_xueqiu(market: str) -> pd.DataFrame:
    import akshare as ak

    df = ak.stock_hot_follow_xq(symbol="最热门")
    if df is None or df.empty:
        return pd.DataFrame()
    if "股票代码" not in df.columns or "股票简称" not in df.columns:
        return pd.DataFrame()
    out = df[["股票代码", "股票简称"]].copy()
    out.columns = ["代码", "名称"]
    out["代码"] = out["代码"].map(_normalize_list_code)
    out["名称"] = out["名称"].astype(str).str.strip()
    out = out[out["代码"].map(lambda x: _match_market(x, market))]
    out = out[out["名称"] != ""]
    out["来源"] = "雪球"
    return out


def cmd_all_stocks(args):
    """获取全市场股票列表（新浪/腾讯/雪球 多源兜底）"""
    session = _build_session()
    session.trust_env = False

    merged = []
    source_errors = {}

    try:
        sina_df = _fetch_all_stocks_sina(session, args.market)
        if not sina_df.empty:
            merged.append(sina_df)
    except Exception as e:
        source_errors["新浪"] = str(e)

    try:
        tx_df = _fetch_all_stocks_tencent(args.market)
        if not tx_df.empty:
            merged.append(tx_df)
    except Exception as e:
        source_errors["腾讯"] = str(e)

    try:
        xq_df = _fetch_all_stocks_xueqiu(args.market)
        if not xq_df.empty:
            merged.append(xq_df)
    except Exception as e:
        source_errors["雪球"] = str(e)

    if not merged:
        if source_errors:
            detail = " | ".join([f"{k}: {v}" for k, v in source_errors.items()])
            print(f"获取股票列表失败：{detail}")
            sys.exit(1)
        print("未获取到股票列表数据")
        return

    raw_df = pd.concat(merged, ignore_index=True)
    raw_df = raw_df[raw_df["代码"].notna() & raw_df["名称"].notna()]
    raw_df["代码"] = raw_df["代码"].astype(str).str.strip()
    raw_df["名称"] = raw_df["名称"].astype(str).str.strip()
    raw_df = raw_df[(raw_df["代码"] != "") & (raw_df["名称"] != "")]
    raw_df = raw_df[raw_df["代码"].map(lambda x: _match_market(x, args.market))]

    source_summary = (
        raw_df.groupby("来源", as_index=False)
        .size()
        .rename(columns={"size": "数量"})
        .sort_values("数量", ascending=False)
    )

    df = raw_df.drop_duplicates(subset=["代码"], keep="first")
    df = df[["代码", "名称"]].sort_values("代码").reset_index(drop=True)

    if df.empty:
        print("未获取到股票列表数据")
        return

    if args.output_json:
        payload = {
            "meta": {
                "market": args.market or "all",
                "total": int(len(df)),
                "sources": source_summary.to_dict(orient="records"),
            },
            "data": df.to_dict(orient="records"),
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        market_label = {"sh": "上海", "sz": "深圳"}.get(args.market, "全市场")
        src_text = ", ".join([f"{r['来源']}:{r['数量']}" for _, r in source_summary.iterrows()])
        print(f"【{market_label}股票列表】共 {len(df)} 只  数据源：{src_text}")
        print(df.to_string(index=False))


# ============ 交易日历 ============
def _trade_dates_from_eastmoney(session: requests.Session, start: str, end: str) -> pd.DataFrame:
    """东方财富交易日历"""
    try:
        params = {
            "sortColumns": "TRADE_DATE",
            "sortTypes": "-1",
            "pageSize": 500,
            "pageNumber": 1,
            "reportName": "RPT_TRADE_DATE",
            "columns": "TRADE_DATE",
            "filter": f'(TRADE_DATE>="{start}")(TRADE_DATE<="{end}")'
        }
        r = session.get(EM_PERFORMANCE_URL, params=params, timeout=15)
        payload = r.json()
        
        if payload.get("result") and payload["result"].get("data"):
            records = payload["result"]["data"]
            df = pd.DataFrame(records)
            if "TRADE_DATE" in df.columns:
                df = df.rename(columns={"TRADE_DATE": "date"})
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                df["is_trading_day"] = "1"
                return df[["date", "is_trading_day"]]
    except Exception:
        pass
    return pd.DataFrame()


def _trade_dates_from_sina(session: requests.Session, start: str, end: str) -> pd.DataFrame:
    """新浪交易日历（通过 akshare 接口逻辑）"""
    try:
        import akshare as ak
        cal = ak.tool_trade_date_hist_sina()
        if cal is not None and not cal.empty:
            cal = cal.rename(columns={"trade_date": "date"})
            cal["date"] = pd.to_datetime(cal["date"])
            s = pd.to_datetime(start)
            e = pd.to_datetime(end)
            df = cal[(cal["date"] >= s) & (cal["date"] <= e)].copy()
            df["is_trading_day"] = "1"
            df["date"] = df["date"].dt.strftime("%Y-%m-%d")
            return df[["date", "is_trading_day"]]
    except Exception:
        pass
    return pd.DataFrame()


def cmd_trade_dates(args):
    session = _build_session()
    start = args.start or "2020-01-01"
    end = args.end or datetime.now().strftime("%Y-%m-%d")
    
    # 优先 akshare(sina源)，再东方财富
    df = _trade_dates_from_sina(session, start, end)
    source = "akshare(sina)"
    if df.empty:
        df = _trade_dates_from_eastmoney(session, start, end)
        source = "东方财富"
    
    if df.empty:
        print(f"未获取到交易日历数据")
        return
    
    if args.output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【交易日历】{start}~{end}  共{len(df)}个交易日  数据源：{source}")
        print(df.to_string(index=False))


# ============ 指数成分 ============
def _index_members_from_akshare(index_type: str) -> pd.DataFrame:
    """akshare 指数成分"""
    try:
        import akshare as ak
        index_code = INDEX_CODE_MAP.get(index_type)
        if not index_code:
            return pd.DataFrame()
        
        # akshare 指数成分接口
        df = ak.index_stock_cons_weight_csindex(symbol=index_code)
        if df is not None and not df.empty:
            # 统一列名
            df = df.rename(columns={
                "成分券代码": "code",
                "成分券名称": "name",
                "权重": "weight",
            })
            return df[["code", "name", "weight"]] if "weight" in df.columns else df[["code", "name"]]
    except Exception:
        pass
    return pd.DataFrame()


def cmd_index_members(args):
    df = _index_members_from_akshare(args.index_type)
    source = "akshare(中证指数)"
    
    if df.empty:
        print(f"未获取到 {args.index_type} 成分股数据（akshare接口暂不可用）")
        return
    
    if args.output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        label_map = {"hs300": "沪深300", "sz50": "上证50", "zz500": "中证500"}
        print(f"【{label_map[args.index_type]}成分股】共{len(df)}只  数据源：{source}")
        print(df.to_string(index=False))


# ============ 分红配送 ============
def _dividend_from_akshare(norm: str, year: str) -> pd.DataFrame:
    """akshare 分红数据"""
    digits = _code_digits(norm)
    try:
        import akshare as ak
        df = ak.stock_dividend_cninfo(symbol=digits)
        if df is not None and not df.empty:
            if year and "分红年度" in df.columns:
                df = df[df["分红年度"].astype(str).str.contains(year)]
            return df
    except Exception:
        pass
    return pd.DataFrame()


def cmd_dividend(args):
    norm = normalize_code(args.dividend)
    
    df = _dividend_from_akshare(norm, args.year)
    
    if df.empty:
        print(f"未获取到 {norm} {args.year}年的分红数据（akshare接口暂不可用）")
        return
    
    if args.output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{norm} 分红配送】{args.year}年  数据源：akshare")
        print(df.to_string(index=False))


# ============ 业绩预告/快报 ============
def _performance_from_akshare(norm: str, kind: str) -> pd.DataFrame:
    """akshare 业绩预告/快报"""
    digits = _code_digits(norm)
    try:
        import akshare as ak
        if kind == "forecast":
            # 业绩预告
            df = ak.stock_em_yjyg(date="")  # 空日期取全部
            if df is not None and not df.empty:
                df = df[df["股票代码"].astype(str).str.contains(digits)]
                return df
        else:
            # 业绩快报
            df = ak.stock_em_yjkb(date="")
            if df is not None and not df.empty:
                df = df[df["股票代码"].astype(str).str.contains(digits)]
                return df
    except Exception:
        pass
    return pd.DataFrame()


def cmd_performance(args):
    norm = normalize_code(args.code)
    
    df = _performance_from_akshare(norm, args.kind)
    
    if df.empty:
        label = "业绩预告" if args.kind == "forecast" else "业绩快报"
        print(f"未获取到 {norm} 的{label}数据（akshare接口暂不可用）")
        return
    
    if args.output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        label = "业绩预告" if args.kind == "forecast" else "业绩快报"
        print(f"【{norm} {label}】数据源：akshare")
        print(df.to_string(index=False))


# ============ 财务指标 ============
def _financials_from_akshare(norm: str) -> pd.DataFrame:
    """akshare 综合财务指标"""
    digits = _code_digits(norm)
    try:
        import akshare as ak
        # 主要财务指标
        df = ak.stock_financial_analysis_indicator(symbol=digits)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame()


def _financial_single_from_akshare(norm: str, func_name: str) -> pd.DataFrame:
    """akshare 单项财务指标"""
    digits = _code_digits(norm)
    try:
        import akshare as ak
        # 使用统一接口获取财务数据
        df = ak.stock_financial_analysis_indicator(symbol=digits)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return pd.DataFrame()


def cmd_financials(args):
    norm = normalize_code(args.financials)
    
    df = _financials_from_akshare(norm)
    
    if df.empty:
        print(f"未获取到 {norm} 的综合财务指标（akshare接口暂不可用）")
        return
    
    if args.output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{norm} 综合财务指标】数据源：akshare")
        print(df.to_string(index=False))


def cmd_financial_single(args):
    norm = normalize_code(args.code)
    
    df = _financial_single_from_akshare(norm, args.func_name)
    
    label_map = {
        "profit": "盈利能力",
        "growth": "成长能力",
        "balance": "偿债能力",
        "cashflow": "现金流量",
        "dupont": "杜邦分析",
    }
    
    if df.empty:
        print(f"未获取到 {norm} 的{label_map[args.func_name]}数据（akshare接口暂不可用）")
        return
    
    if args.output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{norm} {label_map[args.func_name]}】数据源：akshare")
        print(df.to_string(index=False))


# ============ 宏观数据 ============
def _macro_from_akshare(kind: str) -> pd.DataFrame:
    """akshare 宏观数据"""
    try:
        import akshare as ak
        if kind == "deposit":
            df = ak.rate_interbank(market="人民币", symbol="存款利率")
            return df
        elif kind == "loan":
            df = ak.rate_interbank(market="人民币", symbol="贷款利率")
            return df
        elif kind == "reserve":
            df = ak.macro_china_rrr()
            return df
        elif kind == "money":
            df = ak.macro_china_m2_yearly()
            return df
    except Exception:
        pass
    return pd.DataFrame()


def cmd_macro(args):
    df = _macro_from_akshare(args.kind)
    
    label_map = {
        "deposit": "存款基准利率",
        "loan": "贷款基准利率",
        "reserve": "存款准备金率",
        "money": "货币供应量",
    }
    
    if df.empty:
        print(f"未获取到{label_map[args.kind]}数据（akshare接口暂不可用）")
        return
    
    if args.output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{label_map[args.kind]}】数据源：akshare")
        print(df.to_string(index=False))


# ============ 命令行解析 ============
def build_parser():
    p = argparse.ArgumentParser(
        description="A股历史兜底脚本（完全平替Baostock能力，新浪/腾讯/东方财富多源兜底）"
    )
    
    # K线
    p.add_argument("--kline", metavar="CODE", help="历史K线代码")
    p.add_argument("--kline-batch", help="批量历史K线代码，逗号/空格分隔（示例: 600519,000001,300750）")
    p.add_argument("--workers", type=int, default=8, help="批量K线并发线程数，默认8")
    p.add_argument("--retries", type=int, default=2, help="批量K线每只代码重试次数，默认2")
    p.add_argument("--start", help="开始日期 YYYY-MM-DD")
    p.add_argument("--end", help="结束日期 YYYY-MM-DD")
    p.add_argument("--freq", default="1d", choices=["1d", "1w", "1M"], help="K线频率，默认1d")
    p.add_argument("--count", type=int, default=120, help="K线条数，默认120")
    
    # 基本信息
    p.add_argument("--basic", metavar="CODE", help="基本信息代码")
    
    # 行业信息
    p.add_argument("--industry", metavar="CODE", help="行业信息代码")
    p.add_argument("--with-boards", action="store_true", help="查询行业时同步扫描板块归属")
    p.add_argument("--board-scan-limit", type=int, default=80, help="最多扫描多少个板块")
    
    # 全市场股票列表
    p.add_argument("--all-stocks", action="store_true", help="获取全市场股票列表")
    p.add_argument("--market", choices=["sh", "sz"], help="配合 --all-stocks 筛选市场")
    
    # 交易日历
    p.add_argument("--trade-dates", action="store_true", help="获取交易日历")
    
    # 指数成分
    p.add_argument("--hs300", action="store_true", help="沪深300成分股")
    p.add_argument("--sz50", action="store_true", help="上证50成分股")
    p.add_argument("--zz500", action="store_true", help="中证500成分股")
    
    # 分红配送
    p.add_argument("--dividend", metavar="CODE", help="分红配送")
    p.add_argument("--year", help="年度（配合 --dividend 或财务指标）")
    
    # 业绩预告/快报
    p.add_argument("--perf-forecast", metavar="CODE", help="业绩预告")
    p.add_argument("--perf-express", metavar="CODE", help="业绩快报")
    
    # 财务指标
    p.add_argument("--financials", metavar="CODE", help="综合财务指标")
    p.add_argument("--profit", metavar="CODE", help="盈利能力")
    p.add_argument("--growth", metavar="CODE", help="成长能力")
    p.add_argument("--balance", metavar="CODE", help="偿债能力")
    p.add_argument("--cashflow", metavar="CODE", help="现金流量")
    p.add_argument("--dupont", metavar="CODE", help="杜邦分析")
    p.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], help="季度")
    
    # 宏观数据
    p.add_argument("--deposit-rate", action="store_true", help="存款基准利率")
    p.add_argument("--loan-rate", action="store_true", help="贷款基准利率")
    p.add_argument("--reserve-ratio", action="store_true", help="存款准备金率")
    p.add_argument("--money-supply", action="store_true", help="货币供应量")
    
    # 输出格式
    p.add_argument("--json", action="store_true", dest="output_json", help="输出JSON格式")
    
    return p


def main():
    args = build_parser().parse_args()
    
    if args.kline_batch:
        cmd_kline_batch(args)
    elif args.kline:
        cmd_kline(args)
    elif args.basic:
        cmd_basic(args)
    elif args.industry:
        cmd_industry(args)
    elif args.all_stocks:
        cmd_all_stocks(args)
    elif args.trade_dates:
        cmd_trade_dates(args)
    elif args.hs300:
        args.index_type = "hs300"
        cmd_index_members(args)
    elif args.sz50:
        args.index_type = "sz50"
        cmd_index_members(args)
    elif args.zz500:
        args.index_type = "zz500"
        cmd_index_members(args)
    elif args.dividend:
        args.year = args.year or datetime.now().strftime("%Y")
        cmd_dividend(args)
    elif args.perf_forecast:
        args.code = args.perf_forecast
        args.kind = "forecast"
        cmd_performance(args)
    elif args.perf_express:
        args.code = args.perf_express
        args.kind = "express"
        cmd_performance(args)
    elif args.financials:
        cmd_financials(args)
    elif args.profit:
        args.code = args.profit
        args.func_name = "profit"
        cmd_financial_single(args)
    elif args.growth:
        args.code = args.growth
        args.func_name = "growth"
        cmd_financial_single(args)
    elif args.balance:
        args.code = args.balance
        args.func_name = "balance"
        cmd_financial_single(args)
    elif args.cashflow:
        args.code = args.cashflow
        args.func_name = "cashflow"
        cmd_financial_single(args)
    elif args.dupont:
        args.code = args.dupont
        args.func_name = "dupont"
        cmd_financial_single(args)
    elif args.deposit_rate:
        args.kind = "deposit"
        cmd_macro(args)
    elif args.loan_rate:
        args.kind = "loan"
        cmd_macro(args)
    elif args.reserve_ratio:
        args.kind = "reserve"
        cmd_macro(args)
    elif args.money_supply:
        args.kind = "money"
        cmd_macro(args)
    else:
        print("请指定至少一种能力，使用 --help 查看帮助")


if __name__ == "__main__":
    main()
