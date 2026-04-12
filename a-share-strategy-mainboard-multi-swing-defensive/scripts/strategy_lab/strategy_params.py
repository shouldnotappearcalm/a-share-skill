"""Default parameters for mainboard_multi_swing_defensive signal logic."""

from __future__ import annotations

STRATEGY_NAME = "mainboard_multi_swing_defensive"

TREND_PULLBACK_PARAMS: dict = {
    "fast": 8,
    "slow": 20,
    "pullback_ceiling": 1.008,
    "rsi_low": 40,
    "rsi_high": 66,
    "exit_rsi": 74,
    "rsi_period": 14,
}

UNIVERSE_TOP_N_DEFAULT = 120

MAX_BUY_CANDIDATES = 5

REFERENCE_INTRADAY_STOP_PCT = 0.07
