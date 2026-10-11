import json
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

import fetch_history as entry
import fetch_history_fallback as history
import fetch_danginvest as boards
import fetch_industry as industry


@pytest.fixture(autouse=True)
def isolate_cache(tmp_path,monkeypatch):
    monkeypatch.setenv('ASHARE_DATA_CACHE_DIR',str(tmp_path))


def frame():
    return pd.DataFrame({'time':pd.to_datetime(['2026-10-08','2026-10-09']),
                         'open':[10.,11.],'high':[12.,13.],'low':[9.,10.],'close':[11.,12.],'volume':[100,120]})


def test_legacy_adjust_flags_are_forwarded_with_real_semantics():
    assert entry._normalize_argv(['--kline','600519','--adjust','2'])==['--kline','600519','--adjust','qfq']
    assert entry._normalize_argv(['--kline','600519','--adjust','raw'])[-1]=='raw'


def test_adjusted_history_never_uses_raw_sina(monkeypatch):
    monkeypatch.setattr(history,'get_kline_tencent',lambda *a:pd.DataFrame())
    raw=Mock(side_effect=AssertionError('raw source must be skipped'))
    monkeypatch.setattr(history,'get_kline_sina',raw)
    seen=[]
    def backup(*a,**kw):seen.append(kw['adjust']);return frame()
    monkeypatch.setattr(history,'get_kline_eastmoney',backup)
    data,source=history._fetch_kline_with_fallback(None,'sh600519','1d',2,adjust='qfq',no_cache=True)
    assert source=='东财' and seen==['qfq']
    assert data.attrs['adjust_actual']=='qfq'
    raw.assert_not_called()


def test_previous_close_survives_trimming():
    data=history._format_kline_output(frame(),'sh600519',1)
    assert data.iloc[0]['preclose']==11
    assert data.iloc[0]['pctChg']==pytest.approx((12/11-1)*100)


def test_financial_visibility_never_guesses_missing_announcement_date():
    args=SimpleNamespace(start='',end='',year='',quarter=0,count=10,as_of='2026-07-01')
    with pytest.raises(ValueError,match='no announcement dates'):
        history._filter_financial_periods(pd.DataFrame([{'报告期':'2026-06-30'}]),args)
    data=pd.DataFrame([{'报告期':'2026-06-30','公告日期':'2026-08-01'}, {'报告期':'2026-03-31','公告日期':'2026-04-30'}])
    assert history._filter_financial_periods(data,args)['报告期'].tolist()==['2026-03-31']


def test_history_cache_and_no_cache_are_visible(monkeypatch):
    fetch=Mock(return_value=(frame(),'腾讯'))
    monkeypatch.setattr(history,'_fetch_kline_uncached',fetch)
    first,_=history._fetch_kline_with_fallback(None,'sh600519','1d',2)
    second,_=history._fetch_kline_with_fallback(None,'sh600519','1d',2)
    assert not first.attrs['cache']['cache_hit'] and second.attrs['cache']['cache_hit']
    assert fetch.call_count==1
    history._fetch_kline_with_fallback(None,'sh600519','1d',2,no_cache=True)
    assert fetch.call_count==2


def test_stale_snapshot_is_never_reported_fresh(monkeypatch):
    response=Mock();response.json.return_value={'stale':True,'data':{'items':[{'extra':42}]}}
    session=Mock();session.get.return_value=response
    monkeypatch.setattr(boards,'_build_session',lambda _:session)
    obj=boards._get_json('https://example.com',retries=0)
    assert obj['data_quality']=='stale' and obj['data']['items'][0]['extra']==42
    monkeypatch.setattr(boards,'_REQUIRE_FRESH',True)
    with pytest.raises(ValueError,match='fresh data unavailable'):
        boards._get_json('https://example.com',retries=0)


def test_industry_taxonomy_and_native_fields_are_retained(monkeypatch):
    import akshare as ak
    monkeypatch.setattr(ak,'sw_index_first_info',lambda:pd.DataFrame([{'行业代码':'801080.SI','行业名称':'电子','额外字段':42}]))
    result=industry.query_industry(no_cache=True)
    assert result['meta']['taxonomy']=='sw'
    assert result['data'][0]['额外字段']==42
    assert result['meta']['effective_at'] is None
