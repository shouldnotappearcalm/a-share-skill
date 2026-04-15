"""Default parameters for mainboard_multi_swing_defensive signal logic."""

from __future__ import annotations

STRATEGY_NAME = "mainboard_multi_swing_defensive"

TREND_PULLBACK_PARAMS: dict = {
    "fast": 8,
    "slow": 20,
    "pullback_ceiling": 1.008,
    "rsi_low": 42,
    "rsi_high": 72,
    "bull_rsi_low": 42,
    "bull_rsi_high": 72,
    "bear_rsi_low": 30,
    "bear_rsi_high": 60,
    "exit_rsi": 74,
    "rsi_period": 14,
}

ROBUSTNESS_PARAM_GRID: dict = {
    "fast": [8, 10],
    "slow": [20, 30],
    "bull_rsi_low": [40, 42],
    "bull_rsi_high": [70, 72],
}

ENTRY_CONSENSUS_MIN_DEFAULT = 0.67

DEFAULT_ROUNDTRIP_COST_BPS = 45.0

TODO_CONFIRM_ITEMS = [
    "已确认口径: roundtrip_cost_bps=45, entry_consensus_min=0.67",
    "已确认口径: bull_rsi=[42,72], bear_rsi=[30,60]",
]

UNIVERSE_TOP_N_DEFAULT = 120

MAX_BUY_CANDIDATES = 5

REFERENCE_INTRADAY_STOP_PCT = 0.07
