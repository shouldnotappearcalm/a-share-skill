#!/usr/bin/env python3
"""Market data adapter with fully local dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import akshare as ak
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://finance.eastmoney.com",
}
SINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
TENCENT_DAY_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
TENCENT_MIN_URL = "https://ifzq.gtimg.cn/appstock/app/kline/mkline"
TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q="
SINA_FREQ_MAP = {"5m": 5, "15m": 15, "30m": 30, "60m": 60, "1d": 240, "1w": 1200, "1M": 7200}
TENCENT_DAY_FREQ_MAP = {"1d": "day", "1w": "week", "1M": "month"}


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
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
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def _get_json(session: requests.Session, url: str, params=None, timeout: int = 10):
    resp = session.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def normalize_code(code: str) -> str:
    c = (code or "").strip()
    if ".XSHG" in c:
        return "sh" + c.replace(".XSHG", "")
    if ".XSHE" in c:
        return "sz" + c.replace(".XSHE", "")
    if "." in c:
        parts = c.split(".")
        if len(parts) == 2:
            left = parts[0].lower()
            right = parts[1]
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
    norm = normalize_code(code)
    return norm[2:] if norm.startswith(("sh", "sz")) else norm


def infer_limit_ratio(symbol: str, name: str = "") -> float:
    digits = _code_digits(symbol)
    upper_name = str(name or "").upper()
    if digits.startswith(("300", "301", "688", "689")):
        return 0.20
    if "ST" in upper_name:
        return 0.05
    if digits.startswith(("430", "440", "830", "831", "832", "833", "834", "835", "836", "837", "838", "839", "870", "871", "872", "873", "874", "875", "876", "877", "878", "879")):
        return 0.30
    return 0.10


def infer_limit_prices(symbol: str, prev_close: float, name: str = "") -> tuple[Optional[float], Optional[float]]:
    if prev_close <= 0:
        return None, None
    ratio = infer_limit_ratio(symbol, name)
    up = round(prev_close * (1 + ratio), 2)
    down = round(prev_close * (1 - ratio), 2)
    return up, down


def _get_price_sina(session: requests.Session, code: str, count: int, frequency: str) -> pd.DataFrame:
    if frequency not in SINA_FREQ_MAP:
        return pd.DataFrame()
    params = {"symbol": code, "scale": SINA_FREQ_MAP[frequency], "ma": 5, "datalen": count}
    try:
        data = _get_json(session, SINA_KLINE_URL, params=params, timeout=10)
        if not data or isinstance(data, dict):
            return pd.DataFrame()
        df = pd.DataFrame(data)
        if "day" in df.columns:
            df = df.rename(columns={"day": "time"})
        df = df[["time", "open", "high", "low", "close", "volume"]]
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"]).set_index("time")
        df.index.name = ""
        return df
    except Exception:
        return pd.DataFrame()


def _get_price_day_tencent(session: requests.Session, code: str, count: int, frequency: str) -> pd.DataFrame:
    if frequency not in TENCENT_DAY_FREQ_MAP:
        return pd.DataFrame()
    unit = TENCENT_DAY_FREQ_MAP[frequency]
    url = f"{TENCENT_DAY_URL}?param={code},{unit},,,{count},qfq"
    try:
        payload = _get_json(session, url, timeout=10)
        if "data" not in payload or code not in payload["data"]:
            return pd.DataFrame()
        block = payload["data"][code]
        key = "qfq" + unit
        arr = block.get(key) or block.get(unit) or []
        if not arr:
            return pd.DataFrame()
        df = pd.DataFrame(arr, columns=["time", "open", "close", "high", "low", "volume"])
        df = df[["time", "open", "high", "low", "close", "volume"]]
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"]).set_index("time")
        df.index.name = ""
        return df
    except Exception:
        return pd.DataFrame()


def _get_price_min_tencent(session: requests.Session, code: str, count: int, frequency: str) -> pd.DataFrame:
    ts = int(frequency[:-1]) if frequency[:-1].isdigit() else 1
    url = f"{TENCENT_MIN_URL}?param={code},m{ts},,{count}"
    try:
        payload = _get_json(session, url, timeout=10)
        if "data" not in payload or code not in payload["data"]:
            return pd.DataFrame()
        mkey = "m" + str(ts)
        arr = payload["data"][code].get(mkey)
        if not arr:
            return pd.DataFrame()
        df = pd.DataFrame(arr, columns=["time", "open", "close", "high", "low", "volume", "n1", "n2"])
        df = df[["time", "open", "high", "low", "close", "volume"]]
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"]).set_index("time")
        df.index.name = ""
        return df
    except Exception:
        return pd.DataFrame()


def get_price(session: requests.Session, code: str, frequency: str = "1d", count: int = 60) -> pd.DataFrame:
    norm = normalize_code(code)
    if frequency in ("1d", "1w", "1M"):
        df = _get_price_sina(session, norm, count, frequency)
        if not df.empty:
            return df
        df = _get_price_day_tencent(session, norm, count, frequency)
        if not df.empty:
            return df
        if frequency == "1d":
            try:
                ak_df = ak.stock_zh_a_daily(symbol=norm, adjust="")
                if ak_df is not None and not ak_df.empty:
                    ak_df = ak_df.tail(count).copy()
                    ak_df = ak_df.rename(columns={"date": "time"})
                    ak_df["time"] = pd.to_datetime(ak_df["time"], errors="coerce")
                    ak_df = ak_df.set_index("time")
                    ak_df.index.name = ""
                    return ak_df[["open", "high", "low", "close", "volume"]]
            except Exception:
                pass
        return pd.DataFrame()
    if frequency == "1m":
        return _get_price_min_tencent(session, norm, count, frequency)
    df = _get_price_sina(session, norm, count, frequency)
    if not df.empty:
        return df
    return _get_price_min_tencent(session, norm, count, frequency)


def _parse_tencent_quote(line: str) -> Optional[dict]:
    if "~" not in line or len(line) < 50:
        return None
    parts = line.split("~")
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
            "high": float(parts[33]) if parts[33] else 0,
            "low": float(parts[34]) if parts[34] else 0,
            "limit_up": float(parts[47]) if parts[47] else 0,
            "limit_down": float(parts[48]) if len(parts) > 48 and parts[48] else 0,
        }
    except Exception:
        return None


def _fetch_kline_with_fallback(
    session: requests.Session,
    norm: str,
    freq: str,
    fetch_count: int,
    start: str | None = None,
    end: str | None = None,
    retry: int = 2,
):
    last_df = pd.DataFrame()
    for _ in range(max(1, retry)):
        df = _get_price_day_tencent(session, norm, fetch_count, freq)
        if not df.empty:
            out = df.reset_index().rename(columns={"index": "time"})
            return out, "tencent"
        last_df = df
        df = _get_price_sina(session, norm, fetch_count, freq)
        if not df.empty:
            out = df.reset_index().rename(columns={"index": "time"})
            return out, "sina"
        last_df = df
    if freq == "1d":
        try:
            df = ak.stock_zh_a_hist(
                symbol=_code_digits(norm),
                period="daily",
                start_date=pd.to_datetime(start).strftime("%Y%m%d") if start else "",
                end_date=pd.to_datetime(end).strftime("%Y%m%d") if end else "",
                adjust="qfq",
            )
            if df is not None and not df.empty:
                out = df.rename(
                    columns={"日期": "time", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "成交量": "volume"}
                )
                out = out[["time", "open", "high", "low", "close", "volume"]].copy()
                out["time"] = pd.to_datetime(out["time"], errors="coerce")
                out = out.dropna(subset=["time"])
                return out, "eastmoney"
        except Exception:
            pass
    return last_df, None


normalize_history_code = normalize_code
normalize_realtime_code = normalize_code


@dataclass
class Quote:
    symbol: str
    name: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: int
    change_pct: float
    timestamp: str
    source: str
    limit_up: Optional[float] = None
    limit_down: Optional[float] = None


class MarketDataProvider:
    def __init__(self) -> None:
        self._session = _build_session()
        self._realtime_session = _build_session()

    def normalize_symbol(self, symbol: str) -> str:
        norm = normalize_realtime_code(symbol)
        return norm[2:] if norm.startswith(("sh", "sz")) else norm

    def _latest_history_snapshot(self, symbol: str) -> Quote:
        normalized = normalize_realtime_code(symbol)
        day_df = get_price(self._session, normalized, frequency="1d", count=120)
        if day_df is None or day_df.empty or len(day_df) < 2:
            raise ValueError(f"failed to load daily bars for {symbol}")

        prev_close = float(day_df.iloc[-2]["close"]) if len(day_df) >= 2 else float(day_df.iloc[-1]["close"])
        minute_df = get_price(self._session, normalized, frequency="5m", count=320)
        if minute_df is not None and not minute_df.empty:
            latest_bar = minute_df.iloc[-1]
            ts = minute_df.index[-1].strftime("%Y-%m-%d %H:%M:%S")
            open_price = float(latest_bar["open"])
            high_price = float(minute_df["high"].max())
            low_price = float(minute_df["low"].min())
            latest_price = float(latest_bar["close"])
            volume = int(minute_df["volume"].sum())
            source = "tencent/sina-minute"
        else:
            latest_bar = day_df.iloc[-1]
            ts = day_df.index[-1].strftime("%Y-%m-%d 15:00:00")
            open_price = float(latest_bar["open"])
            high_price = float(latest_bar["high"])
            low_price = float(latest_bar["low"])
            latest_price = float(latest_bar["close"])
            volume = int(latest_bar["volume"])
            source = "tencent/sina-daily"

        change_pct = ((latest_price - prev_close) / prev_close * 100.0) if prev_close else 0.0
        return Quote(
            symbol=self.normalize_symbol(symbol),
            name=self.normalize_symbol(symbol),
            price=round(latest_price, 3),
            open=round(open_price, 3),
            high=round(high_price, 3),
            low=round(low_price, 3),
            prev_close=round(prev_close, 3),
            volume=volume,
            change_pct=round(change_pct, 3),
            timestamp=ts,
            source=source,
        )

    def get_quote(self, symbol: str) -> Quote:
        snapshot = self._latest_history_snapshot(symbol)
        normalized = normalize_realtime_code(symbol)
        try:
            response = self._realtime_session.get(f"{TENCENT_QUOTE_URL}{normalized}", timeout=10)
            parsed = _parse_tencent_quote(response.text.strip())
            if parsed:
                snapshot.name = parsed.get("name") or snapshot.name
                snapshot.limit_up = float(parsed["limit_up"]) if parsed.get("limit_up") else None
                snapshot.limit_down = float(parsed["limit_down"]) if parsed.get("limit_down") else None
                snapshot.open = float(parsed.get("open") or snapshot.open)
                snapshot.high = float(parsed.get("high") or snapshot.high)
                snapshot.low = float(parsed.get("low") or snapshot.low)
                snapshot.price = float(parsed.get("price") or snapshot.price)
        except Exception:
            pass
        if snapshot.limit_up is None or snapshot.limit_down is None:
            inferred_up, inferred_down = infer_limit_prices(snapshot.symbol, snapshot.prev_close, snapshot.name)
            snapshot.limit_up = snapshot.limit_up or inferred_up
            snapshot.limit_down = snapshot.limit_down or inferred_down
        return snapshot

    def get_quotes(self, symbols: List[str]) -> Dict[str, Quote]:
        return {self.normalize_symbol(symbol): self.get_quote(symbol) for symbol in symbols}

    def get_history(self, symbol: str, start: str | None = None, end: str | None = None, count: int = 240) -> pd.DataFrame:
        norm = normalize_history_code(symbol)
        fetch_count = max(60, int(count))
        result = _fetch_kline_with_fallback(
            self._session,
            norm,
            "1d",
            fetch_count=fetch_count,
            start=start,
            end=end,
            retry=2,
        )
        df = result[0] if isinstance(result, tuple) else result
        if df is None or df.empty:
            raise ValueError(f"failed to load history for {symbol}")
        out = df.copy()
        if "time" not in out.columns:
            out = out.rename(columns={out.columns[0]: "time"})
        out["time"] = pd.to_datetime(out["time"])
        out = out.sort_values("time").reset_index(drop=True)
        for column in ["open", "high", "low", "close", "volume"]:
            out[column] = pd.to_numeric(out[column], errors="coerce")
        out = out.dropna(subset=["time", "open", "high", "low", "close"])
        if start:
            out = out[out["time"] >= pd.to_datetime(start)]
        if end:
            out = out[out["time"] <= pd.to_datetime(end)]
        return out.tail(count).reset_index(drop=True)

    def get_intraday_bars(self, symbol: str, freq: str = "1m", count: int = 240) -> pd.DataFrame:
        normalized = normalize_realtime_code(symbol)
        df = get_price(self._session, normalized, frequency=freq, count=count)
        if df is None or df.empty:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        out = df.copy().reset_index()
        out = out.rename(columns={out.columns[0]: "time"})
        out = out[["time", "open", "high", "low", "close", "volume"]]
        out["time"] = pd.to_datetime(out["time"])
        for column in ["open", "high", "low", "close", "volume"]:
            out[column] = pd.to_numeric(out[column], errors="coerce")
        out = out.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time").reset_index(drop=True)
        return out
