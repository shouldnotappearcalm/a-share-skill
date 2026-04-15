"""Strategy signal builders."""

from __future__ import annotations

from typing import Callable

import pandas as pd

from .indicators import add_atr, add_breakout_levels, add_ma, add_rsi


def _trend_pullback_rsi_bounds(out: pd.DataFrame, fast: int, slow: int, params: dict) -> tuple[pd.Series, pd.Series]:
    bull_mask = out[f"ma_{fast}"] > out[f"ma_{slow}"]
    bull_low = float(params.get("bull_rsi_low", params.get("rsi_low", 42)))
    bull_high = float(params.get("bull_rsi_high", params.get("rsi_high", 68)))
    bear_low = float(params.get("bear_rsi_low", 30))
    bear_high = float(params.get("bear_rsi_high", 60))
    low = pd.Series(bear_low, index=out.index, dtype="float64")
    high = pd.Series(bear_high, index=out.index, dtype="float64")
    low.loc[bull_mask] = bull_low
    high.loc[bull_mask] = bull_high
    return low, high


def breakout_momentum(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    lookback = int(params.get("lookback", 20))
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 30))
    out = add_breakout_levels(add_ma(df, [fast, slow]), lookback)
    out["entry"] = (out["close"] > out[f"breakout_high_{lookback}"]) & (out[f"ma_{fast}"] > out[f"ma_{slow}"])
    out["exit"] = (out["close"] < out[f"ma_{fast}"]) | (out["close"] < out[f"breakout_low_{lookback}"])
    out["score"] = ((out["close"] / out[f"breakout_high_{lookback}"]) - 1.0).fillna(0.0)
    return out


def trend_pullback(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 30))
    rsi_period = int(params.get("rsi_period", 14))
    out = add_rsi(add_ma(df, [fast, slow]), rsi_period)
    rsi_key = f"rsi_{rsi_period}"
    rsi_low, rsi_high = _trend_pullback_rsi_bounds(out, fast, slow, params)
    out["entry"] = (
        (out[f"ma_{fast}"] > out[f"ma_{slow}"])
        & (out["close"] > out[f"ma_{slow}"])
        & (out["close"] < out[f"ma_{fast}"] * float(params.get("pullback_ceiling", 1.01)))
        & (out[rsi_key] >= rsi_low)
        & (out[rsi_key] <= rsi_high)
    )
    out["exit"] = (out["close"] < out[f"ma_{slow}"]) | (out[rsi_key] > float(params.get("exit_rsi", 72)))
    out["score"] = ((out[f"ma_{fast}"] / out[f"ma_{slow}"]) - 1.0).fillna(0.0)
    return out


def event_rotation(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    fast = int(params.get("fast", 5))
    slow = int(params.get("slow", 20))
    ret_fast = int(params.get("ret_fast", 5))
    ret_slow = int(params.get("ret_slow", 10))
    out = add_ma(df, [fast, slow])
    out[f"ret_{ret_fast}"] = out["close"].pct_change(ret_fast)
    out[f"ret_{ret_slow}"] = out["close"].pct_change(ret_slow)
    out["entry"] = (
        (out[f"ret_{ret_fast}"] > float(params.get("min_ret_5", 0.04)))
        & (out["close"] > out[f"ma_{fast}"])
        & (out[f"ma_{fast}"] > out[f"ma_{slow}"])
    )
    out["exit"] = (out[f"ret_{ret_fast}"] < 0) | (out["close"] < out[f"ma_{slow}"])
    out["score"] = (out[f"ret_{ret_fast}"].fillna(0.0) * 0.6 + out[f"ret_{ret_slow}"].fillna(0.0) * 0.4)
    return out


def mean_revert(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    out = add_rsi(add_ma(df, [5, 20]), 6)
    rsi_key = "rsi_6"
    out["dist_ma20"] = out["close"] / out["ma_20"] - 1.0
    out["entry"] = (out[rsi_key] < float(params.get("entry_rsi", 18))) & (out["dist_ma20"] < float(params.get("max_dist", -0.06)))
    out["exit"] = (out[rsi_key] > float(params.get("exit_rsi", 55))) | (out["close"] >= out["ma_5"])
    out["score"] = (-out["dist_ma20"]).fillna(0.0)
    return out


def low_vol_breakout(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    lookback = int(params.get("lookback", 15))
    out = add_breakout_levels(add_atr(add_ma(df, [10, 30]), 14), lookback)
    atr_key = "atr_pct_14"
    out["atr_rank"] = out[atr_key].rolling(20).rank(pct=True)
    out["entry"] = (
        (out["atr_rank"] < float(params.get("atr_rank_max", 0.35)))
        & (out["close"] > out[f"breakout_high_{lookback}"])
        & (out["ma_10"] > out["ma_30"])
    )
    out["exit"] = (out["close"] < out["ma_10"]) | (out["close"] < out[f"breakout_low_{lookback}"])
    out["score"] = (1.0 - out["atr_rank"].fillna(1.0)) + ((out["close"] / out[f"breakout_high_{lookback}"]) - 1.0).fillna(0.0)
    return out


def mainboard_leader_trend(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    out = add_breakout_levels(add_atr(add_ma(df, [5, 20, 60]), 14), int(params.get("lookback", 20)))
    out["ret_20"] = out["close"].pct_change(20)
    out["entry"] = (
        (out["ma_5"] > out["ma_20"])
        & (out["ma_20"] > out["ma_60"])
        & (out["ret_20"] > float(params.get("min_ret_20", 0.15)))
        & (out["close"] > out[f"breakout_high_{int(params.get('lookback', 20))}"])
    )
    out["exit"] = (out["close"] < out["ma_20"]) | ((out["close"] / out["ma_20"] - 1.0) < float(params.get("max_dist_ma20", -0.04)))
    out["score"] = out["ret_20"].fillna(0.0) + ((out["ma_5"] / out["ma_20"]) - 1.0).fillna(0.0)
    return out


def event_rotation_defensive(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    out = add_atr(add_ma(df, [5, 20]), 14)
    out["ret_5"] = out["close"].pct_change(5)
    out["ret_10"] = out["close"].pct_change(10)
    atr_key = "atr_pct_14"
    out["entry"] = (
        (out["ret_5"] > float(params.get("min_ret_5", 0.035)))
        & (out["ret_10"] > float(params.get("min_ret_10", 0.06)))
        & (out[atr_key] < float(params.get("max_atr_pct", 0.085)))
        & (out["close"] > out["ma_5"])
    )
    out["exit"] = (
        (out["ret_5"] < float(params.get("exit_ret_5", -0.01)))
        | (out["close"] < out["ma_20"])
        | (out[atr_key] > float(params.get("exit_atr_pct", 0.10)))
    )
    out["score"] = out["ret_10"].fillna(0.0) + out["ret_5"].fillna(0.0) - out[atr_key].fillna(0.0)
    return out


def main_event_swing(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    out = add_breakout_levels(add_rsi(add_ma(df, [5, 20, 60]), 10), int(params.get("lookback", 15)))
    out["ret_10"] = out["close"].pct_change(10)
    out["ret_20"] = out["close"].pct_change(20)
    breakout_key = f"breakout_high_{int(params.get('lookback', 15))}"
    out["entry"] = (
        (out["ma_5"] > out["ma_20"])
        & (out["ma_20"] > out["ma_60"])
        & (out["ret_10"] > float(params.get("min_ret_10", 0.08)))
        & (out["ret_20"] > float(params.get("min_ret_20", 0.15)))
        & (out["close"] >= out[breakout_key] * float(params.get("breakout_buffer", 0.995)))
        & (out["rsi_10"] < float(params.get("max_rsi", 78)))
    )
    out["exit"] = (
        (out["close"] < out["ma_20"])
        | (out["ret_10"] < float(params.get("exit_ret_10", -0.03)))
        | (out["rsi_10"] > float(params.get("exit_rsi", 84)))
    )
    out["score"] = out["ret_20"].fillna(0.0) + ((out["ma_5"] / out["ma_20"]) - 1.0).fillna(0.0)
    return out


def leader_rotation(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    fast = int(params.get("fast", 10))
    mid = int(params.get("mid", 20))
    slow = int(params.get("slow", 60))
    lookback = int(params.get("lookback", 20))
    out = add_breakout_levels(add_rsi(add_ma(df, [fast, mid, slow]), 14), lookback)
    out["ret_10"] = out["close"].pct_change(10)
    out["ret_20"] = out["close"].pct_change(20)
    out["ret_60"] = out["close"].pct_change(60)
    out["entry"] = (
        (out[f"ma_{fast}"] > out[f"ma_{mid}"])
        & (out[f"ma_{mid}"] > out[f"ma_{slow}"])
        & (out["ret_20"] > float(params.get("min_ret_20", 0.10)))
        & (out["ret_60"] > float(params.get("min_ret_60", 0.25)))
        & (out["close"] >= out[f"breakout_high_{lookback}"] * float(params.get("breakout_buffer", 0.99)))
        & (out["rsi_14"].between(float(params.get("min_rsi", 52)), float(params.get("max_rsi", 82))))
    )
    out["exit"] = (
        (out["close"] < out[f"ma_{mid}"])
        | (out["ret_10"] < float(params.get("exit_ret_10", -0.03)))
        | (out["rsi_14"] > float(params.get("exit_rsi", 88)))
    )
    out["score"] = (
        out["ret_20"].fillna(0.0) * 0.5
        + out["ret_60"].fillna(0.0) * 0.5
        + ((out[f"ma_{fast}"] / out[f"ma_{mid}"]) - 1.0).fillna(0.0)
    )
    return out


def adaptive_rotation(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    fast = int(params.get("fast", 10))
    slow = int(params.get("slow", 30))
    lookback = int(params.get("lookback", 20))
    out = add_breakout_levels(add_rsi(add_ma(df, [fast, slow]), 14), lookback)
    out["ret_5"] = out["close"].pct_change(5)
    out["ret_20"] = out["close"].pct_change(20)
    trend_breakout = (
        (out[f"ma_{fast}"] > out[f"ma_{slow}"])
        & (out["ret_20"] > float(params.get("min_breakout_ret_20", 0.12)))
        & (out["close"] >= out[f"breakout_high_{lookback}"] * float(params.get("breakout_buffer", 0.99)))
    )
    trend_pullback_signal = (
        (out[f"ma_{fast}"] > out[f"ma_{slow}"])
        & (out["close"] > out[f"ma_{slow}"])
        & (out["close"] < out[f"ma_{fast}"] * float(params.get("pullback_ceiling", 1.01)))
        & (out["rsi_14"].between(float(params.get("rsi_low", 42)), float(params.get("rsi_high", 68))))
    )
    out["entry"] = trend_breakout | trend_pullback_signal
    out["exit"] = (
        (out["close"] < out[f"ma_{slow}"])
        | (out["ret_5"] < float(params.get("exit_ret_5", -0.03)))
        | (out["rsi_14"] > float(params.get("exit_rsi", 82)))
    )
    out["score"] = (
        out["ret_20"].fillna(0.0) * 0.6
        + ((out[f"ma_{fast}"] / out[f"ma_{slow}"]) - 1.0).fillna(0.0) * 0.4
    )
    return out


STRATEGY_BUILDERS: dict[str, Callable[[pd.DataFrame, dict], pd.DataFrame]] = {
    "adaptive_rotation": adaptive_rotation,
    "breakout_momentum": breakout_momentum,
    "trend_pullback": trend_pullback,
    "event_rotation": event_rotation,
    "event_rotation_defensive": event_rotation_defensive,
    "leader_rotation": leader_rotation,
    "main_event_swing": main_event_swing,
    "mean_revert": mean_revert,
    "low_vol_breakout": low_vol_breakout,
    "mainboard_leader_trend": mainboard_leader_trend,
}
