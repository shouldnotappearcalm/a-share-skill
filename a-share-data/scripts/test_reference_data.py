"""Contract tests for raw data, failure visibility, source scope and cache behavior."""
import json
from types import SimpleNamespace

import pandas as pd
import pytest

import reference_common as common
import fetch_stock_concepts as concepts
import fetch_corporate_actions as actions
import fetch_market_details as market
import fetch_realtime as realtime


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("ASHARE_DATA_CACHE_DIR", str(tmp_path))


def result(rows, total=None, pages=1):
    return {"success": True, "result": {"data": rows, "count": len(rows) if total is None else total, "pages": pages}}


def pool(rows=None, date="20261009", total=None):
    rows = rows if rows is not None else [{"c": "600519", "n": "贵州茅台", "p": 1234000, "fbt": 93000,
                                          "lbt": 145900, "zbc": 3, "zttj": {"days": 2, "ct": 1}, "new_field": 42}]
    return {"rc": 0, "data": {"pool": rows, "qdate": date, "tc": len(rows) if total is None else total}}


def test_ths_all_categories_reasons_and_unknown_ids():
    html = '<h1>公司</h1><h1>601899</h1>'
    for category, cell in [("常规概念", '<td class="gnName" clid="123">黄金</td>'),
                           ("新兴概念", '<td class="gnStockList">新题材</td>'),
                           ("其他概念", '<td class="gnStockList">沪股通</td>')]:
        html += f'<h2>{category}</h2><table class="gnContent"><tr>{cell}<td>其他</td></tr><tr><td colspan="2">供应商原文 <b>未改写</b></td></tr></table>'
    rows, meta = concepts.parse_ths_concepts(html, "601899")
    assert [r["category"] for r in rows] == ["常规概念", "新兴概念", "其他概念"]
    assert rows[0]["concept_code"] == "123" and rows[1]["concept_code"] is None
    assert all(r["reason"] == "供应商原文 未改写" and r["evidence_date"] is None for r in rows)
    assert "<b>未改写</b>" in rows[0]["raw"]["reason_html"]
    assert meta["tables_parsed"] == 3
    with pytest.raises(common.UpstreamError, match="identity"):
        concepts.parse_ths_concepts(html, "600519")
    with pytest.raises(common.UpstreamError, match="tables absent"):
        concepts.parse_ths_concepts('<h1>601899</h1>blocked', "601899")


def test_precise_concepts_truncation_is_partial_and_not_cached(monkeypatch):
    calls = []
    def fetch(url, deadline, **kwargs):
        calls.append(kwargs["params"])
        return result([{"SECURITY_CODE": "601899", "BOARD_NAME": "黄金", "SELECTED_BOARD_REASON": "原文", "extra": 42}], 101, 3)
    monkeypatch.setattr(concepts, "get_json", fetch)
    for _ in range(2):
        output = concepts.query_stock_concepts("601899", "eastmoney", max_pages=1)
        assert output["status"] == "partial" and output["meta"]["coverage_limited"]
        assert output["data"][0]["raw"]["extra"] == 42
    assert len(calls) == 2 and '(IS_PRECISE="1")' in calls[0]["filter"]


def test_concept_source_failure_keeps_other_taxonomy(monkeypatch):
    monkeypatch.setattr(concepts, "ths_concepts", lambda *a: ([{"name": "黄金", "source": "ths_f10", "raw": {}}], {"coverage_limited": False}))
    def fail(*a):
        raise common.UpstreamError("blocked")
    monkeypatch.setattr(concepts, "eastmoney_concepts", fail)
    output = concepts.query_stock_concepts("601899", no_cache=True)
    assert output["status"] == "partial" and output["meta"]["coverage_limited"]
    assert len(output["data"]) == 1


def test_api_http_success_with_provider_error_is_not_empty(monkeypatch):
    monkeypatch.setattr(common, "get_json", lambda *a, **kw: {"success": False, "code": 9501, "message": "bad fields"})
    output = actions.query_corporate_actions("repurchase", "301011", no_cache=True)
    assert output["status"] == "unavailable" and "9501" in output["error"]


def test_full_unlock_pagination_and_native_units(monkeypatch):
    pages = []
    def fetch(url, deadline, **kwargs):
        page = kwargs["params"]["pageNumber"]; pages.append(page)
        rows = [{"SECURITY_CODE": "688981", "FREE_DATE": "2026-10-12 00:00:00", "CURRENT_FREE_SHARES": 12.5, "extra": i}
                for i in range(100 if page == 1 else 63)]
        return result(rows, 163, 2)
    monkeypatch.setattr(common, "get_json", fetch)
    output = actions.query_corporate_actions(start="20261012", end="20261110", no_cache=True)
    assert output["status"] == "ok" and len(output["data"]) == 163 and pages == [1, 2]
    assert output["data"][0]["raw"]["CURRENT_FREE_SHARES"] == 12.5
    assert "10,000" in output["meta"]["raw_units"]
    limited = actions.query_corporate_actions(start="20261012", end="20261110", max_pages=1, no_cache=True)
    assert limited["status"] == "partial" and limited["meta"]["total"] == 163


def test_mid_pagination_failure_preserves_data(monkeypatch):
    def fetch(url, deadline, **kwargs):
        if kwargs["params"]["pageNumber"] == 1:
            return result([{"SECURITY_CODE": "688981", "FREE_DATE": "2026-10-12"}], 2, 2)
        raise TimeoutError("source timed out")
    monkeypatch.setattr(common, "get_json", fetch)
    output = actions.query_corporate_actions(code="688981", no_cache=True)
    assert output["status"] == "partial" and len(output["data"]) == 1 and output["meta"]["errors"]


def test_holder_window_uses_disclosure_date_not_change_period(monkeypatch):
    seen = []
    def fetch(url, deadline, **kwargs):
        seen.append(kwargs["params"])
        return result([{"SECURITY_CODE": "603519", "NOTICE_DATE": "2026-10-09", "END_DATE": "2026-09-01", "DIRECTION": "减持", "CHANGE_NUM": 10}])
    monkeypatch.setattr(common, "get_json", fetch)
    output = actions.query_corporate_actions("holder_changes", "603519", "20261001", "20261010", direction="decrease", no_cache=True)
    assert output["status"] == "ok" and output["data"][0]["event_date"] == "2026-10-09"
    assert output["data"][0]["raw"]["END_DATE"] == "2026-09-01"
    assert "NOTICE_DATE>=" in seen[0]["filter"] and '(DIRECTION="减持")' in seen[0]["filter"]
    assert "END_DATE" not in seen[0]["sortColumns"]


def test_repurchase_plan_does_not_become_execution(monkeypatch):
    row = {"DIM_SCODE": "301011", "UPDATEDATE": "2026-10-09", "REPURPROGRESS": "001", "JESX": 1000000, "REPURAMOUNT": None}
    monkeypatch.setattr(common, "get_json", lambda *a, **kw: result([row]))
    output = actions.query_corporate_actions("repurchase", "301011", no_cache=True)
    assert output["data"][0]["progress_label"] == "董事会预案"
    assert output["data"][0]["raw"] == row and row["REPURAMOUNT"] is None


def test_event_validation_prevents_unbounded_scan_or_ignored_filters(monkeypatch):
    with pytest.raises(ValueError, match="bounded"):
        actions.query_corporate_actions("repurchase")
    with pytest.raises(ValueError, match="366"):
        actions.query_corporate_actions(start="20250101", end="20261001")
    monkeypatch.setattr(common, "get_json", lambda *a, **kw: result([{"DIM_SCODE": "600519", "UPDATEDATE": "2026-10-09"}]))
    assert actions.query_corporate_actions("repurchase", "301011", no_cache=True)["status"] == "unavailable"


def test_pool_real_date_raw_fields_and_explicit_date_rejection(monkeypatch):
    monkeypatch.setattr(market, "get_json", lambda *a, **kw: pool())
    output = market.query_market_pool(date="20261011", allow_date_fallback=True, no_cache=True)
    assert output["meta"]["trade_date"] == "2026-10-09" and output["meta"]["date_fallback"]
    assert output["data"][0]["raw"] == pool()["data"]["pool"][0]
    rejected = market.query_market_pool(date="20261011", no_cache=True)
    assert rejected["status"] == "unavailable" and "returned 2026-10-09" in rejected["meta"]["source_attempts"][0]["error"]


@pytest.mark.parametrize("response", [{"rc": 0, "data": None}, pool([])])
def test_no_snapshot_cannot_claim_requested_date_is_actual(monkeypatch, response):
    monkeypatch.setattr(market, "get_json", lambda *a, **kw: response)
    output = market.query_market_pool(date="20200102", no_cache=True)
    assert output["status"] == "empty" and output["meta"]["trade_date"] is None
    assert output["meta"]["date_verified"] is False


def test_historical_pool_qdate_is_not_the_snapshot_date(monkeypatch):
    monkeypatch.setattr(market, "get_json", lambda *a, **kw: pool())
    monkeypatch.setattr(market, "_ths_pool", lambda *a: ([{"code": "600519"}], {"coverage_limited": False, "trade_date": "2026-10-08"}))
    output = market.query_market_pool(date="20261008", no_cache=True)
    assert output["status"] == "ok" and output["meta"]["trade_date"] == "2026-10-08"
    assert output["meta"]["provider_qdate"] == "2026-10-09"
    assert output["meta"]["date_check"]["source"] == "ths_dated_pool"


def test_unverifiable_historical_date_preserves_raw_but_is_partial(monkeypatch):
    monkeypatch.setattr(market, "get_json", lambda *a, **kw: pool())
    def fail(*args):
        raise TimeoutError("date control unavailable")
    monkeypatch.setattr(market, "_ths_pool", fail)
    output = market.query_market_pool(date="20261008", no_cache=True)
    assert output["status"] == "partial" and output["meta"]["trade_date"] is None
    assert output["meta"]["date_verified"] is False
    assert output["data"][0]["raw"] == pool()["data"]["pool"][0]


def test_market_scope_does_not_silently_drop_beijing(monkeypatch):
    monkeypatch.setattr(market, "get_json", lambda *a, **kw: pool([{"c": "600519", "n": "贵州茅台"}, {"c": "920627", "n": "测试"}]))
    assert len(market.query_market_pool(date="20261009", no_cache=True)["data"]) == 2
    scoped = market.query_market_pool(date="20261009", market="shsz", no_cache=True)
    assert len(scoped["data"]) == 1 and scoped["meta"]["market"] == "shsz"
    assert scoped["meta"]["total"] == 2 and scoped["meta"]["selected_total"] == 1
    with pytest.raises(ValueError, match="SH/SZ"):
        market.query_market_pool(source="ths")


def test_auto_fallback_respects_scope_and_preserves_diagnostics(monkeypatch):
    calls = []
    def fail(*a):
        calls.append("em"); raise common.UpstreamError("blocked")
    def ths(*a):
        calls.append("ths")
        return [{"code": "600519"}], {"source": "ths", "trade_date": "2026-10-09", "market": "shsz", "coverage_limited": False}
    monkeypatch.setattr(market, "_eastmoney_pool", fail)
    monkeypatch.setattr(market, "_ths_pool", ths)
    assert market.query_market_pool(date="20261009", no_cache=True)["status"] == "unavailable" and calls == ["em"]
    output = market.query_market_pool(date="20261009", allow_partial_scope=True, no_cache=True)
    assert output["status"] == "partial" and output["meta"]["scope_limited"]
    assert output["meta"]["source_attempts"][0]["error"].endswith("blocked")


def test_ths_pagination_and_row_date_validation(monkeypatch):
    def fetch(url, deadline, **kwargs):
        return {"status_code": 0, "data": {"date": "20261009", "info": [{"code": "600519", "first_limit_up_time": 1791509400}], "page": {"total": 2}}}
    # Timestamp intentionally belongs to Oct 9 Shanghai; explicit mismatch below must fail.
    from datetime import datetime
    timestamp = int(datetime(2026, 10, 9, 9, 30, tzinfo=common.TZ).timestamp())
    obj = fetch(None, None); obj["data"]["info"][0]["first_limit_up_time"] = timestamp
    monkeypatch.setattr(market, "get_json", lambda *a, **kw: obj)
    output = market.query_market_pool(date="20261009", source="ths", market="shsz", max_pages=1, no_cache=True)
    assert output["status"] == "partial" and output["meta"]["total"] == 2
    obj["data"]["date"] = "20261008"
    assert market.query_market_pool(date="20261008", source="ths", market="shsz", no_cache=True)["status"] == "unavailable"


def seat(reason="原因一"):
    return {"SECURITY_CODE": "002317", "TRADE_DATE": "2026-10-09 00:00:00", "BUY": 100, "SELL": 20, "NET": 80,
            "OPERATEDEPT_NAME": "同一营业部", "EXPLANATION": reason, "TRADE_ID": reason, "extra": 42}


def test_seat_protocol_and_multiple_reasons_are_retained(monkeypatch):
    seen = []
    def fetch(url, deadline, **kwargs):
        seen.append(kwargs["params"])
        return result([seat(), seat("原因二")])
    monkeypatch.setattr(common, "get_json", fetch)
    output = market.query_lhb_seats("002317", "20261009", no_cache=True)
    assert output["status"] == "ok" and len(output["data"]) == 4
    assert {p["sortColumns"] for p in seen} == {"BUY", "SELL"}
    assert {r["raw"]["EXPLANATION"] for r in output["data"]} == {"原因一", "原因二"}
    assert all(r["raw"]["BUY"] - r["raw"]["SELL"] == r["raw"]["NET"] for r in output["data"])


def test_seat_side_failure_is_partial(monkeypatch):
    def fetch(url, deadline, **kwargs):
        return result([seat()]) if kwargs["params"]["sortColumns"] == "BUY" else {"success": False, "code": 9501}
    monkeypatch.setattr(common, "get_json", fetch)
    output = market.query_lhb_seats("002317", "20261009", no_cache=True)
    assert output["status"] == "partial" and len(output["data"]) == 1 and output["meta"]["coverage_limited"]


def test_pool_cache_and_bypass(monkeypatch):
    calls = []
    def fetch(*a, **kw):
        calls.append(1); return pool()
    monkeypatch.setattr(market, "get_json", fetch)
    assert market.query_market_pool(date="20261009")["meta"]["cache_hit"] is False
    assert market.query_market_pool(date="20261009")["meta"]["cache_hit"] is True
    market.query_market_pool(date="20261009", no_cache=True)
    assert len(calls) == 2
    truncated = market.query_market_pool(date="20261009", limit=1, no_cache=True)
    assert truncated["data"][0]["raw"]["new_field"] == 42


def test_legacy_json_retains_seal_times_and_full_lhb_fields(monkeypatch, capsys):
    raw_pool = {"代码": "600519", "名称": "贵州茅台", "成交额": 100000000, "首次封板时间": "093000", "最后封板时间": "145900", "炸板次数": 3, "涨停统计": "2/1"}
    raw_lhb = {"代码": "002317", "名称": "测试", "龙虎榜净买额": 100000, "龙虎榜买入额": 120000, "龙虎榜卖出额": 20000, "上榜原因": "原因"}
    monkeypatch.setattr(realtime, "_ak", lambda: SimpleNamespace(stock_zt_pool_em=lambda **kw: pd.DataFrame([raw_pool]), stock_lhb_detail_em=lambda **kw: pd.DataFrame([raw_lhb])))
    realtime.cmd_limit_up_pool("20261009", 20, True)
    output = json.loads(capsys.readouterr().out)[0]
    assert all(output[key] == value for key, value in raw_pool.items()) and output["成交额(亿)"] == 1
    realtime.cmd_lhb("20261009", "20261009", 20, True)
    output = json.loads(capsys.readouterr().out)[0]
    assert all(output[key] == value for key, value in raw_lhb.items()) and output["净买额(万)"] == 10
