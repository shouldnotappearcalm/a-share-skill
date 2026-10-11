#!/usr/bin/env python3
"""Explicit industry taxonomies, directories, real constituents and index history."""
import argparse
import json
from datetime import date

try:
    from .data_runtime import cached_fetch, call_source
except ImportError:
    from data_runtime import cached_fetch, call_source


def query_industry(action='directory', taxonomy='sw', level=1, symbol='', start='', end='', no_cache=False):
    if action not in ('directory','members','history') or taxonomy not in ('sw','eastmoney_industry','eastmoney_concept') or level not in (1,2,3):
        raise ValueError('invalid action/taxonomy/level')
    if action != 'directory' and not symbol:
        raise ValueError('members/history requires provider-native industry code or name')
    for value in (start,end):
        if value:date.fromisoformat(value)
    def load(_):
        import akshare as ak
        if taxonomy == 'sw':
            if action == 'directory':
                frame = getattr(ak, {1:'sw_index_first_info',2:'sw_index_second_info',3:'sw_index_third_info'}[level])()
                source = 'legulegu/SW classification'
            elif action == 'members':
                frame = ak.sw_index_third_cons(symbol=symbol if symbol.endswith('.SI') else symbol+'.SI')
                source = 'legulegu/SW constituents'
            else:
                frame = ak.index_hist_sw(symbol=symbol.removesuffix('.SI'), period='day')
                source = 'SW Research index history'
        else:
            prefix = 'stock_board_industry' if taxonomy == 'eastmoney_industry' else 'stock_board_concept'
            if action == 'directory':
                frame = getattr(ak, prefix+'_name_em')()
            elif action == 'members':
                frame = getattr(ak, prefix+'_cons_em')(symbol=symbol)
            else:
                frame = getattr(ak, prefix+'_hist_em')(symbol=symbol,start_date=(start or '20200101').replace('-',''),end_date=(end or date.today().isoformat()).replace('-',''),period='日k',adjust='')
            source = 'Eastmoney'
        if frame is None or frame.empty:
            raise ValueError('source returned no industry records')
        if action == 'history':
            column = next((name for name in ('日期','date','时间') if name in frame),None)
            if column:
                dates=frame[column].astype(str).str[:10]
                if start:frame=frame[dates>=start]
                if end:frame=frame[frame[column].astype(str).str[:10]<=end]
        data=json.loads(frame.to_json(orient='records',force_ascii=False,date_format='iso'))
        return {'status':'ok' if data else 'empty','data':data,'meta':{
            'source':source,'taxonomy':taxonomy,'taxonomy_version':None,'level':level if action=='directory' and taxonomy=='sw' else None,
            'action':action,'symbol':symbol or None,'count':len(data),'effective_at':None,
            'membership_basis':'current provider snapshot; no historical membership guarantee',
            'price_basis':'raw' if action=='history' and taxonomy.startswith('eastmoney') else 'provider_index_level' if action=='history' else None}}
    key=f'industry:{action}:{taxonomy}:{level}:{symbol}:{start}:{end}'
    result,cache=cached_fetch(key,lambda old:call_source(lambda:load(old),20),86400 if action=='directory' else 300,no_cache)
    result['meta'].update(cache)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--action',choices=['directory','members','history'],default='directory')
    p.add_argument('--taxonomy',choices=['sw','eastmoney_industry','eastmoney_concept'],default='sw')
    p.add_argument('--level',type=int,choices=[1,2,3],default=1)
    p.add_argument('--symbol',default='')
    p.add_argument('--start',default='');p.add_argument('--end',default='')
    p.add_argument('--no-cache',action='store_true');p.add_argument('--json',action='store_true')
    args=p.parse_args()
    try:result=query_industry(args.action,args.taxonomy,args.level,args.symbol,args.start,args.end,args.no_cache)
    except Exception as exc:
        print(json.dumps({'status':'unavailable','error':f'{type(exc).__name__}: {exc}','data':[]},ensure_ascii=False));raise SystemExit(1)
    print(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2))


if __name__=='__main__':main()
