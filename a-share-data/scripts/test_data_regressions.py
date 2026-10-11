"""Offline regression coverage for the data failures found in the live audit."""
import contextlib
import io
import json
import time
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from datetime import datetime
from unittest.mock import patch

import pandas as pd

import check_data_health as health
import fetch_company_news as company
import fetch_history_fallback as history
import fetch_realtime as realtime
import fetch_stock_events as events
import fetch_technical as technical


class MarketDataTests(unittest.TestCase):
    def test_ambiguous_bare_codes_are_stocks(self):
        self.assertEqual(realtime.normalize_code("000001"), "sz000001")
        self.assertEqual(realtime.normalize_code("000002"), "sz000002")
        self.assertEqual(realtime.normalize_code("sh000001"), "sh000001")
        self.assertEqual(realtime.normalize_code("000001.XSHG"), "sh000001")

    def test_technical_prices_preserve_both_provider_column_orders(self):
        row = {"open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100}
        for fields in (["open", "high", "low", "close", "volume"], ["open", "close", "high", "low", "volume"]):
            frame = pd.DataFrame([row], columns=fields, index=pd.to_datetime(["2026-10-09"]))
            with patch.object(technical, "get_price", return_value=frame):
                actual = technical.fetch_kline("600519", "1d", 1).iloc[0]
            for key, value in row.items():
                self.assertEqual(actual[key], value)

    def test_closed_session_compares_last_two_daily_closes(self):
        daily = pd.DataFrame({"open": [9., 10.], "high": [10., 12.], "low": [8., 9.],
                              "close": [10., 11.], "volume": [100., 120.]}, index=pd.to_datetime(["2020-01-02", "2020-01-03"]))
        def price(code, frequency, count):
            return daily if frequency == "1d" else None
        for fn, arg in [(realtime.cmd_quote, "600519"), (realtime.cmd_multi_quote, "600519,000001")]:
            output = io.StringIO()
            with patch.object(realtime, "get_price", side_effect=price), contextlib.redirect_stdout(output):
                fn(arg, True)
            actual = json.loads(output.getvalue())
            for row in actual if isinstance(actual, list) else [actual]:
                self.assertEqual(row["昨收"], 10)
                self.assertEqual(row["涨跌幅(%)"], 10)

    def test_financial_categories_are_not_identical_tables(self):
        data = pd.DataFrame([{"报告期": "2026-06-30", "营业总收入": 100, "归母净利润": 20,
                              "营收同比增长率(%)": 5, "资产负债率(%)": 30, "每股经营现金流": 2}])
        with patch.object(history, "_financials_from_akshare", return_value=data):
            growth = history._financial_single_from_akshare("sh600519", "growth")
            cashflow = history._financial_single_from_akshare("sh600519", "cashflow")
        self.assertIn("营收同比增长率(%)", growth)
        self.assertNotIn("归母净利润", growth)
        self.assertIn("每股经营现金流", cashflow)
        self.assertNotIn("资产负债率(%)", cashflow)

    def test_complete_primary_stock_list_skips_fallback_and_caches(self):
        args = SimpleNamespace(market=None, no_cache=False, output_json=True)
        frame = pd.DataFrame([{"代码": "sh600519", "名称": "贵州茅台", "来源": "新浪"}])
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(history, "__file__", str(Path(directory) / "scripts" / "history.py")), \
             patch.object(history, "_fetch_all_stocks_sina", return_value=frame) as primary, \
             patch.object(history, "_fetch_all_stocks_exchange") as fallback:
            outputs = []
            for _ in range(2):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    history.cmd_all_stocks(args)
                outputs.append(json.loads(output.getvalue()))
        self.assertEqual(primary.call_count, 1)
        fallback.assert_not_called()
        self.assertEqual(outputs[0]["data"], outputs[1]["data"])
        self.assertFalse(outputs[0]["meta"]["cache_hit"])
        self.assertTrue(outputs[1]["meta"]["cache_hit"])

    def test_stock_list_failure_uses_independent_exchange_fallback(self):
        args = SimpleNamespace(market=None, no_cache=True, output_json=True)
        frame = pd.DataFrame([{"代码": "sz000001", "名称": "平安银行", "来源": "交易所-AKShare"}])
        output = io.StringIO()
        with patch.object(history, "_fetch_all_stocks_sina", side_effect=RuntimeError("failed")), \
             patch.object(history, "_fetch_all_stocks_exchange", return_value=frame), \
             contextlib.redirect_stdout(output):
            history.cmd_all_stocks(args)
        result = json.loads(output.getvalue())
        self.assertEqual(result["data"][0]["名称"], "平安银行")
        self.assertIn("新浪", result["meta"]["errors"])


class CompanyInformationTests(unittest.TestCase):
    def row(self, title, stamp="2026-10-10 09:00:00", kind="news", provider="eastmoney_news", url="https://example.com/a", summary=""):
        return dict(title=title, published_at=stamp, kind=kind, provider=provider, url=url, summary=summary, publisher="source")

    def test_time_relevance_and_disclosure_deduplication(self):
        rows = [self.row("胜宏科技：重大合同", kind="announcement", provider="cninfo"),
                self.row("胜宏科技：重大合同", kind="announcement", provider="eastmoney_announcements", url="https://example.com/b"),
                self.row("市场综述", url="https://example.com/c", summary="胜宏科技参与行业反弹"),
                self.row("胜宏科技去年业绩", "2025-10-10", url="https://example.com/d"),
                self.row("胜宏科技未来新闻", "2026-10-12", url="https://example.com/e"),
                self.row("胜宏科技：员工持股计划公告", url="https://example.com/f")]
        start, end = datetime(2026, 10, 5, tzinfo=company.TZ), datetime(2026, 10, 11, tzinfo=company.TZ)
        actual = company.normalize_items(rows, "300476", "胜宏科技", start, end)
        self.assertEqual(len(actual), 3)
        self.assertEqual(actual[0]["provider"], "cninfo")
        self.assertTrue(all("categories" not in r for r in actual))
        self.assertEqual(len(company.normalize_items(rows, "300476", "胜宏科技", start, end, title_only=True)), 2)

    def test_partial_source_failure_preserves_available_disclosures(self):
        row = self.row("胜宏科技：回购股份", kind="announcement", provider="eastmoney_announcements")
        with patch.object(company, "news_em", return_value=([], False)), \
             patch.object(company, "announcements_cninfo", side_effect=RuntimeError("upstream unavailable")), \
             patch.object(company, "announcements_em", return_value=([row], False)):
            result = company.build_payload("300476", "胜宏科技", no_cache=True, now=datetime(2026, 10, 11, tzinfo=company.TZ))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["data"]), 1)
        self.assertTrue(any(d.get("error") for d in result["meta"]["sources"]))

    def test_shanghai_index_code_is_not_ping_an_bank_news(self):
        rows = [self.row("上证指数000001收涨", url="https://example.com/index"),
                self.row("平安银行发布AI管理办法", url="https://example.com/bank")]
        actual = company.normalize_items(rows, "000001", "平安银行",
                                         datetime(2026, 10, 5, tzinfo=company.TZ),
                                         datetime(2026, 10, 11, tzinfo=company.TZ), title_only=True)
        self.assertEqual([r["title"] for r in actual], ["平安银行发布AI管理办法"])

    def test_dividend_year_filters_actual_provider_column(self):
        frame = pd.DataFrame([{"报告时间": "2025年报", "派息比例": 5}, {"报告时间": "2024年报", "派息比例": 4}])
        with patch.object(history, "_code_digits", return_value="600519"), \
             patch("akshare.stock_dividend_cninfo", return_value=frame):
            actual = history._dividend_from_akshare("sh600519", "2025")
        self.assertEqual(actual["报告时间"].tolist(), ["2025年报"])

    def test_deadline_does_not_wait_for_stuck_provider(self):
        def stuck(*args):
            time.sleep(0.25)
            return [], False
        started = time.monotonic()
        with patch.object(company, "news_em", side_effect=stuck):
            result = company.build_payload("300476", "胜宏科技", scope="news", max_seconds=0.03, no_cache=True)
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(all(s["status"] == "timeout" for s in result["meta"]["sources"]))

    def test_news_without_company_name_is_preserved_for_agent_judgment(self):
        rows = [self.row("全球算力需求增长", summary="涉及多家供应商")]
        result = company.normalize_items(rows, "300476", "胜宏科技",
                                         datetime(2026, 10, 5, tzinfo=company.TZ),
                                         datetime(2026, 10, 11, tzinfo=company.TZ))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["matched_in"], "upstream_query")
        self.assertNotIn("categories", result[0])

    def test_news_paging_stops_at_query_window(self):
        rows = [{"title": "新闻", "date": "2026-09-30 09:00:00", "code": str(i)} for i in range(50)]
        response = SimpleNamespace(text=json.dumps({"result": {"cmsArticleWebOld": rows}}))
        with patch.object(company, "request", return_value=response) as request:
            result, truncated = company.news_em("胜宏科技", time.monotonic() + 5, 5,
                                                 datetime(2026, 10, 5, tzinfo=company.TZ))
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(result), 50)
        self.assertFalse(truncated)

    def test_http_cache_reuses_data_across_different_output_queries(self):
        response = company.requests.Response()
        response.status_code = 200
        response._content = b'{"result": []}'
        response.encoding = "utf-8"
        company._HTTP.no_cache = False
        with tempfile.TemporaryDirectory() as directory, patch.object(company, "CACHE", Path(directory)), \
             patch.object(company, "http_session") as session:
            session.return_value.request.return_value = response
            first = company.request("GET", "https://example.com", time.monotonic() + 5, params={"q": "company"})
            second = company.request("GET", "https://example.com", time.monotonic() + 5, params={"q": "company"})
            self.assertEqual(first.json(), second.json())
            self.assertEqual(session.return_value.request.call_count, 1)

    def test_plain_news_never_becomes_contract_fallback(self):
        recent = {"status": "ok", "meta": {}, "data": [dict(title="胜宏科技上涨", summary="", published_at="2026-10-10", publisher="source", url="https://example.com", kind="news", provider="eastmoney_news", categories=[])]}
        with patch.object(company, "build_payload", return_value=recent):
            result = events.query_news_categories("300476", "胜宏科技", 5, time.time() + 5)
        self.assertEqual(result["major_contracts"]["items"], [])
        self.assertEqual(result["regulatory"]["items"], [])
        self.assertEqual(result["regulatory"]["status"], "unclassified")


class HealthChecksTests(unittest.TestCase):
    def test_failed_and_empty_payloads_are_not_success(self):
        self.assertEqual(health.assess({"data": []})[0], "empty")
        self.assertEqual(health.assess({"data": [], "errors": ["timeout"]})[0], "error")
        self.assertEqual(health.assess({"results": [{"ok": False}, {"ok": True}]})[0], "partial")

    def test_invalid_ohlc_and_stale_snapshots_are_detected(self):
        self.assertTrue(health.quality_findings("technical", [{"open": 10, "close": 12, "high": 9, "low": 8}]))
        self.assertTrue(health.quality_findings("boards_sub", {"meta": {"stale": True}, "data": [1]}))


if __name__ == "__main__":
    unittest.main()
