#!/usr/bin/env python3
"""Unit tests for market universe board filters."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


from paper_trading.market_data import filter_a_share_universe  # type: ignore  # noqa: E402


class MarketUniverseFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.df = pd.DataFrame(
            [
                {"代码": "600000", "名称": "浦发银行", "成交额": "100"},
                {"代码": "000001", "名称": "平安银行", "成交额": "90"},
                {"代码": "300750", "名称": "宁德时代", "成交额": "80"},
                {"代码": "301183", "名称": "东田微", "成交额": "70"},
                {"代码": "688041", "名称": "海光信息", "成交额": "60"},
                {"代码": "002594", "名称": "比亚迪", "成交额": "50"},
                {"代码": "600001", "名称": "*ST示例", "成交额": "40"},
                {"代码": "300001", "名称": "退市示例退", "成交额": "30"},
            ]
        )

    def test_mainboard_filter_excludes_growth_and_star_boards(self) -> None:
        out = filter_a_share_universe(self.df, include_growth_boards=False, top_n=0)

        self.assertEqual(out, ["600000", "000001", "002594"])

    def test_all_market_filter_keeps_growth_and_star_boards(self) -> None:
        out = filter_a_share_universe(self.df, include_growth_boards=True, top_n=0)

        self.assertEqual(out, ["600000", "000001", "300750", "301183", "688041", "002594"])


if __name__ == "__main__":
    unittest.main()
