"""Indicator helpers."""

from __future__ import annotations

import pandas as pd


def add_ma(df: pd.DataFrame, periods: list[int]) -> pd.DataFrame:
    out = df.copy()
    for period in periods:
        out[f"ma_{period}"] = out["close"].rolling(period).mean()
    return out


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    delta = out["close"].diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    out[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return out


def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    prev_close = out["close"].shift(1)
    true_range = pd.concat(
        [
            (out["high"] - out["low"]).abs(),
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out[f"atr_{period}"] = true_range.rolling(period).mean()
    out[f"atr_pct_{period}"] = out[f"atr_{period}"] / out["close"]
    return out


def add_breakout_levels(df: pd.DataFrame, lookback: int) -> pd.DataFrame:
    out = df.copy()
    out[f"breakout_high_{lookback}"] = out["high"].shift(1).rolling(lookback).max()
    out[f"breakout_low_{lookback}"] = out["low"].shift(1).rolling(lookback).min()
    return out
