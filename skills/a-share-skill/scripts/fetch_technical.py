#!/usr/bin/env python3
"""
A股技术指标分析脚本
数据源：腾讯/新浪实时K线（直接API）+ MyTT（指标计算）

依赖安装：pip install MyTT pandas numpy requests

支持指标：MA / EMA / MACD / KDJ / RSI / WR / BOLL / BIAS / CCI / ATR / DMI / TAQ

用法示例：
  python3 fetch_technical.py 600519
  python3 fetch_technical.py 000001 --freq 1d --count 120
  python3 fetch_technical.py 300750 --indicators MA,MACD,KDJ,RSI,BOLL
  python3 fetch_technical.py 600519 --freq 15m --count 60 --indicators MACD,KDJ
  python3 fetch_technical.py 600519 --json
"""

import argparse
import json
import sys

import numpy as np
import pandas as pd

from fetch_realtime import get_price, normalize_code


def fetch_kline(code: str, freq: str, count: int) -> pd.DataFrame:
    normalized = normalize_code(code)
    df = get_price(normalized, frequency=freq, count=count)
    if df is None or df.empty:
        print(f"未找到 {code} 的K线数据", file=sys.stderr)
        sys.exit(1)
    df = df.reset_index()
    df.columns = ["time", "open", "close", "high", "low", "volume"]
    return df


def calc_indicators(df: pd.DataFrame, indicators: list) -> pd.DataFrame:
    try:
        from MyTT import MA, EMA, MACD, KDJ, RSI, WR, BOLL, BIAS, CCI, ATR, DMI, TAQ
    except ImportError:
        print("请先安装：pip install MyTT", file=sys.stderr)
        sys.exit(1)

    CLOSE = df["close"].values.astype(float)
    HIGH = df["high"].values.astype(float)
    LOW = df["low"].values.astype(float)
    VOL = df["volume"].values.astype(float)

    for ind in indicators:
        ind = ind.strip().upper()
        try:
            if ind == "MA":
                df["MA5"] = MA(CLOSE, 5)
                df["MA10"] = MA(CLOSE, 10)
                df["MA20"] = MA(CLOSE, 20)
                df["MA60"] = MA(CLOSE, 60)
            elif ind == "EMA":
                df["EMA12"] = EMA(CLOSE, 12)
                df["EMA26"] = EMA(CLOSE, 26)
            elif ind == "MACD":
                dif, dea, macd_val = MACD(CLOSE)
                df["MACD_DIF"] = dif
                df["MACD_DEA"] = dea
                df["MACD"] = macd_val
            elif ind == "KDJ":
                k, d, j = KDJ(CLOSE, HIGH, LOW)
                df["KDJ_K"] = k
                df["KDJ_D"] = d
                df["KDJ_J"] = j
            elif ind == "RSI":
                df["RSI"] = RSI(CLOSE)
            elif ind == "WR":
                wr1, wr2 = WR(CLOSE, HIGH, LOW)
                df["WR10"] = wr1
                df["WR6"] = wr2
            elif ind == "BOLL":
                up, mid, low_b = BOLL(CLOSE)
                df["BOLL_UP"] = up
                df["BOLL_MID"] = mid
                df["BOLL_LOW"] = low_b
            elif ind == "BIAS":
                b1, b2, b3 = BIAS(CLOSE)
                df["BIAS6"] = b1
                df["BIAS12"] = b2
                df["BIAS24"] = b3
            elif ind == "CCI":
                df["CCI"] = CCI(CLOSE, HIGH, LOW)
            elif ind == "ATR":
                df["ATR"] = ATR(CLOSE, HIGH, LOW)
            elif ind == "DMI":
                pdi, mdi, adx, adxr = DMI(CLOSE, HIGH, LOW)
                df["DMI_PDI"] = pdi
                df["DMI_MDI"] = mdi
                df["DMI_ADX"] = adx
                df["DMI_ADXR"] = adxr
            elif ind == "TAQ":
                up, mid, down = TAQ(HIGH, LOW, 20)
                df["TAQ_UP"] = up
                df["TAQ_MID"] = mid
                df["TAQ_DOWN"] = down
        except Exception as e:
            print(f"计算 {ind} 失败：{e}", file=sys.stderr)

    for col in df.columns:
        if df[col].dtype in [np.float64, np.float32]:
            df[col] = df[col].round(3)

    return df


def interpret_signals(df: pd.DataFrame, indicators: list) -> list:
    signals = []
    if df.empty:
        return signals

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None

    if "MA5" in df.columns and "MA10" in df.columns and "MA20" in df.columns:
        ma5, ma10, ma20 = last.get("MA5"), last.get("MA10"), last.get("MA20")
        if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
            if ma5 > ma10 > ma20:
                signals.append("均线多头排列（MA5>MA10>MA20），趋势偏强")
            elif ma5 < ma10 < ma20:
                signals.append("均线空头排列（MA5<MA10<MA20），趋势偏弱")

    if "MACD_DIF" in df.columns and prev is not None:
        dif_now, dea_now = last.get("MACD_DIF"), last.get("MACD_DEA")
        dif_prev, dea_prev = prev.get("MACD_DIF"), prev.get("MACD_DEA")
        if all(pd.notna(x) for x in [dif_now, dea_now, dif_prev, dea_prev]):
            if dif_prev < dea_prev and dif_now > dea_now:
                signals.append("MACD 金叉，短期买入信号")
            elif dif_prev > dea_prev and dif_now < dea_now:
                signals.append("MACD 死叉，短期卖出信号")
            if dif_now > 0 and dea_now > 0:
                signals.append("MACD 在零轴上方，多头市场")
            elif dif_now < 0 and dea_now < 0:
                signals.append("MACD 在零轴下方，空头市场")

    if "KDJ_K" in df.columns:
        k, d = last.get("KDJ_K"), last.get("KDJ_D")
        if pd.notna(k) and pd.notna(d):
            if k > 80 and d > 80:
                signals.append(f"KDJ 超买区（K={k:.1f}），注意回调风险")
            elif k < 20 and d < 20:
                signals.append(f"KDJ 超卖区（K={k:.1f}），关注反弹机会")

    if "RSI" in df.columns:
        rsi = last.get("RSI")
        if pd.notna(rsi):
            if rsi > 80:
                signals.append(f"RSI={rsi:.1f} 超买，谨慎追高")
            elif rsi < 20:
                signals.append(f"RSI={rsi:.1f} 超卖，可关注低吸机会")
            else:
                signals.append(f"RSI={rsi:.1f} 处于正常区间")

    if "BOLL_UP" in df.columns:
        close = last.get("close", last.get("收盘"))
        up, mid, low_b = last.get("BOLL_UP"), last.get("BOLL_MID"), last.get("BOLL_LOW")
        if all(pd.notna(x) for x in [close, up, mid, low_b]):
            if close > up:
                signals.append(f"价格突破布林带上轨（{up:.2f}），强势但注意压力")
            elif close < low_b:
                signals.append(f"价格跌破布林带下轨（{low_b:.2f}），弱势但关注支撑")
            else:
                signals.append(f"布林带：上轨{up:.2f} 中轨{mid:.2f} 下轨{low_b:.2f}")

    return signals


def main():
    parser = argparse.ArgumentParser(description="A股技术指标分析 (ashares + MyTT)")
    parser.add_argument("code", help="股票代码，如 600519 / sh600519 / sh.600519")
    parser.add_argument("--freq", default="1d",
                        help="K线频率：1m/5m/15m/30m/60m/1d/1w/1M（默认1d）")
    parser.add_argument("--count", type=int, default=120,
                        help="K线条数，建议>=120以保证指标准确（默认120）")
    parser.add_argument("--indicators", default="MA,MACD,KDJ,RSI,BOLL",
                        help="指标列表，逗号分隔（默认MA,MACD,KDJ,RSI,BOLL）\n"
                             "可选：MA/EMA/MACD/KDJ/RSI/WR/BOLL/BIAS/CCI/ATR/DMI/TAQ")
    parser.add_argument("--no-signal", action="store_true", help="不输出信号解读")
    parser.add_argument("--json", action="store_true", dest="output_json", help="输出JSON格式")
    args = parser.parse_args()

    indicators = [i.strip() for i in args.indicators.split(",") if i.strip()]

    df = fetch_kline(args.code, args.freq, args.count)
    df = calc_indicators(df, indicators)

    display_count = min(50, len(df))
    df_display = df.tail(display_count).copy()

    if args.output_json:
        print(df_display.to_json(orient="records", force_ascii=False, date_format="iso"))
        return

    print(f"【{args.code} 技术指标】频率={args.freq}  条数={len(df)}  指标={','.join(indicators)}")
    print(f"数据源：Ashare(腾讯/新浪) + MyTT  （显示最近{display_count}条）")
    print(df_display.to_string(index=False))

    if not args.no_signal:
        signals = interpret_signals(df, indicators)
        if signals:
            print("\n【信号解读】")
            for s in signals:
                print(f"  · {s}")


if __name__ == "__main__":
    main()
