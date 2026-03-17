#!/usr/bin/env python3
"""
A股历史数据脚本（历史K线 / 财务报表 / 指数成分 / 宏观经济）
数据源：Baostock（延迟数据，当日17:30后更新）

依赖安装：pip install baostock pandas

注意：历史K线数据在当日交易日 17:30 后才完成入库；分钟线在次日 11:00 完成入库。

用法示例：
  python3 fetch_history.py --kline sh.600519 --start 2026-01-01 --end 2026-03-18
  python3 fetch_history.py --kline 000001 --start 2025-01-01 --end 2026-01-01 --adjust 2
  python3 fetch_history.py --basic sh.600519
  python3 fetch_history.py --financials sh.600519 --start 2024-01-01 --end 2026-01-01
  python3 fetch_history.py --profit sh.600519 --year 2024 --quarter 4
  python3 fetch_history.py --dividend sh.600519 --year 2024
  python3 fetch_history.py --hs300
  python3 fetch_history.py --industry --code sh.600519
  python3 fetch_history.py --trade-dates --start 2026-03-01 --end 2026-03-18
  python3 fetch_history.py --deposit-rate
  python3 fetch_history.py --money-supply --period month
"""

import argparse
import json
import sys
from contextlib import contextmanager
from datetime import datetime

import baostock as bs
import pandas as pd


@contextmanager
def bs_session():
    lg = bs.login()
    if lg.error_code != "0":
        print(f"Baostock 登录失败：{lg.error_msg}", file=sys.stderr)
        sys.exit(1)
    try:
        yield
    finally:
        bs.logout()


def normalize_code(code: str) -> str:
    code = code.strip()
    if "." in code and code.split(".")[0].lower() in ("sh", "sz"):
        return code.lower()
    if code.isdigit():
        prefix = "sh" if code.startswith("6") else "sz"
        return f"{prefix}.{code}"
    return code


def _bs_to_df(rs) -> pd.DataFrame:
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields) if rows else pd.DataFrame()


def cmd_kline(code: str, start: str, end: str, freq: str, adjust: str, limit: int, output_json: bool):
    code = normalize_code(code)
    fields = "date,code,open,high,low,close,preclose,volume,amount,pctChg,turn,peTTM,pbMRQ"
    with bs_session():
        rs = bs.query_history_k_data_plus(code, fields, start_date=start, end_date=end,
                                           frequency=freq, adjustflag=adjust)
        df = _bs_to_df(rs)
    if df.empty:
        print(f"未找到 {code} 在 {start}~{end} 的K线数据")
        return
    df = df.tail(limit)
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        adj_label = {"1": "后复权", "2": "前复权", "3": "不复权"}.get(adjust, adjust)
        print(f"【{code} 历史K线】{start}~{end}  频率={freq}  复权={adj_label}  共{len(df)}条  数据源：Baostock")
        print(df.to_string(index=False))


def cmd_basic(code: str, output_json: bool):
    code = normalize_code(code)
    with bs_session():
        rs = bs.query_stock_basic(code=code)
        df = _bs_to_df(rs)
    if df.empty:
        print(f"未找到 {code} 的基本信息")
        return
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{code} 基本信息】数据源：Baostock")
        for col in df.columns:
            print(f"  {col}: {df[col].values[0]}")


def _fetch_financial(func, code: str, year: str, quarter: int) -> pd.DataFrame:
    with bs_session():
        rs = func(code=code, year=year, quarter=quarter)
        return _bs_to_df(rs)


def cmd_financial_single(func_name: str, label: str, code: str, year: str, quarter: int, output_json: bool):
    code = normalize_code(code)
    func_map = {
        "profit": bs.query_profit_data,
        "operation": bs.query_operation_data,
        "growth": bs.query_growth_data,
        "balance": bs.query_balance_data,
        "cashflow": bs.query_cash_flow_data,
        "dupont": bs.query_dupont_data,
    }
    df = _fetch_financial(func_map[func_name], code, year, quarter)
    if df.empty:
        print(f"未找到 {code} {year}Q{quarter} 的{label}数据")
        return
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{code} {label}】{year}年第{quarter}季度  数据源：Baostock")
        print(df.to_string(index=False))


def cmd_financials(code: str, start: str, end: str, output_json: bool):
    code = normalize_code(code)
    try:
        s = datetime.strptime(start, "%Y-%m-%d")
        e = datetime.strptime(end, "%Y-%m-%d")
    except ValueError:
        print("日期格式错误，请使用 YYYY-MM-DD")
        sys.exit(1)

    years = set(str(y) for y in range(s.year, e.year + 1))
    all_records = []

    with bs_session():
        for year in sorted(years):
            for q in [1, 2, 3, 4]:
                q_start = datetime(int(year), (q - 1) * 3 + 1, 1)
                if q_start > e:
                    continue
                record = {"code": code, "year": year, "quarter": q}
                for prefix, func in [
                    ("profit", bs.query_profit_data),
                    ("operation", bs.query_operation_data),
                    ("growth", bs.query_growth_data),
                    ("balance", bs.query_balance_data),
                    ("cashflow", bs.query_cash_flow_data),
                    ("dupont", bs.query_dupont_data),
                ]:
                    try:
                        rs = func(code=code, year=year, quarter=q)
                        if rs.error_code == "0" and rs.next():
                            row = rs.get_row_data()
                            for i, f in enumerate(rs.fields):
                                record[f"{prefix}_{f}"] = row[i] if i < len(row) else None
                    except Exception:
                        pass
                if len(record) > 3:
                    all_records.append(record)

    if not all_records:
        print(f"未找到 {code} 在 {start}~{end} 的财务数据")
        return

    df = pd.DataFrame(all_records)
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{code} 综合财务指标】{start}~{end}  共{len(df)}条季报  数据源：Baostock")
        print(df.to_string(index=False))


def cmd_performance(kind: str, code: str, start: str, end: str, output_json: bool):
    code = normalize_code(code)
    with bs_session():
        if kind == "express":
            rs = bs.query_performance_express_report(code=code, start_date=start, end_date=end)
            label = "业绩快报"
        else:
            rs = bs.query_forecast_report(code=code, start_date=start, end_date=end)
            label = "业绩预告"
        df = _bs_to_df(rs)
    if df.empty:
        print(f"未找到 {code} 在 {start}~{end} 的{label}")
        return
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{code} {label}】{start}~{end}  数据源：Baostock")
        print(df.to_string(index=False))


def cmd_dividend(code: str, year: str, output_json: bool):
    code = normalize_code(code)
    with bs_session():
        rs = bs.query_dividend_data(code=code, year=year, yearType="report")
        df = _bs_to_df(rs)
    if df.empty:
        print(f"未找到 {code} {year}年的分红数据")
        return
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{code} 分红配送】{year}年  数据源：Baostock")
        print(df.to_string(index=False))


def cmd_industry(code: str, output_json: bool):
    with bs_session():
        rs = bs.query_stock_industry(code=normalize_code(code) if code else None)
        df = _bs_to_df(rs)
    if df.empty:
        print("未找到行业数据")
        return
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        label = f"{code} 所属行业" if code else "全市场行业分类"
        print(f"【{label}】数据源：Baostock")
        print(df.to_string(index=False))


def cmd_index_members(index: str, date: str, output_json: bool):
    func_map = {
        "hs300": bs.query_hs300_stocks,
        "sz50": bs.query_sz50_stocks,
        "zz500": bs.query_zz500_stocks,
    }
    label_map = {"hs300": "沪深300", "sz50": "上证50", "zz500": "中证500"}
    func = func_map.get(index)
    if not func:
        print(f"不支持的指数：{index}，可选：hs300 / sz50 / zz500")
        sys.exit(1)
    with bs_session():
        rs = func(date=date) if date else func()
        df = _bs_to_df(rs)
    if df.empty:
        print(f"未找到 {index} 成分股数据")
        return
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{label_map[index]}成分股】{'日期=' + date if date else '最新'}  共{len(df)}只  数据源：Baostock")
        print(df.to_string(index=False))


def cmd_trade_dates(start: str, end: str, output_json: bool):
    with bs_session():
        rs = bs.query_trade_dates(start_date=start, end_date=end)
        df = _bs_to_df(rs)
    if df.empty:
        print("未找到交易日数据")
        return
    trading = df[df["is_trading_day"] == "1"] if "is_trading_day" in df.columns else df
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【交易日历】{start or '默认'}~{end or '今日'}  共{len(trading)}个交易日  数据源：Baostock")
        print(df.to_string(index=False))


def cmd_macro(kind: str, start: str, end: str, period: str, output_json: bool):
    with bs_session():
        if kind == "deposit":
            rs = bs.query_deposit_rate_data(start_date=start, end_date=end)
            label = "存款基准利率"
        elif kind == "loan":
            rs = bs.query_loan_rate_data(start_date=start, end_date=end)
            label = "贷款基准利率"
        elif kind == "reserve":
            rs = bs.query_required_reserve_ratio_data(start_date=start, end_date=end)
            label = "存款准备金率"
        elif kind == "money" and period == "month":
            rs = bs.query_money_supply_data_month(start_date=start, end_date=end)
            label = "货币供应量（月）"
        elif kind == "money" and period == "year":
            rs = bs.query_money_supply_data_year(start_date=start, end_date=end)
            label = "货币供应量（年）"
        else:
            print("不支持的宏观数据类型")
            sys.exit(1)
        df = _bs_to_df(rs)
    if df.empty:
        print(f"未找到{label}数据")
        return
    if output_json:
        print(df.to_json(orient="records", force_ascii=False))
    else:
        print(f"【{label}】数据源：Baostock")
        print(df.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="A股历史数据 (Baostock)")

    parser.add_argument("--kline", metavar="CODE", help="历史K线（代码如 sh.600519 或 600519）")
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    parser.add_argument("--freq", default="d", help="K线频率：d/w/m/5/15/30/60（默认d）")
    parser.add_argument("--adjust", default="3", help="复权：1后复权 2前复权 3不复权（默认3）")
    parser.add_argument("--limit", type=int, default=500, help="最大返回行数（默认500）")

    parser.add_argument("--basic", metavar="CODE", help="股票基本信息")

    parser.add_argument("--financials", metavar="CODE", help="综合财务指标（6类合并）")
    parser.add_argument("--profit", metavar="CODE", help="盈利能力")
    parser.add_argument("--operation", metavar="CODE", help="营运能力")
    parser.add_argument("--growth", metavar="CODE", help="成长能力")
    parser.add_argument("--balance", metavar="CODE", help="偿债能力（资产负债）")
    parser.add_argument("--cashflow", metavar="CODE", help="现金流量")
    parser.add_argument("--dupont", metavar="CODE", help="杜邦分析")
    parser.add_argument("--year", help="财务数据年份，如 2024")
    parser.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], help="财务数据季度 1-4")

    parser.add_argument("--perf-express", metavar="CODE", help="业绩快报")
    parser.add_argument("--perf-forecast", metavar="CODE", help="业绩预告")

    parser.add_argument("--dividend", metavar="CODE", help="分红配送")

    parser.add_argument("--industry", action="store_true", help="行业分类")
    parser.add_argument("--code", help="配合 --industry 指定股票代码")

    parser.add_argument("--hs300", action="store_true", help="沪深300成分股")
    parser.add_argument("--sz50", action="store_true", help="上证50成分股")
    parser.add_argument("--zz500", action="store_true", help="中证500成分股")
    parser.add_argument("--date", help="指数成分股日期 YYYY-MM-DD（默认最新）")

    parser.add_argument("--trade-dates", action="store_true", help="交易日历")

    parser.add_argument("--deposit-rate", action="store_true", help="存款基准利率")
    parser.add_argument("--loan-rate", action="store_true", help="贷款基准利率")
    parser.add_argument("--reserve-ratio", action="store_true", help="存款准备金率")
    parser.add_argument("--money-supply", action="store_true", help="货币供应量")
    parser.add_argument("--period", default="month", choices=["month", "year"], help="货币供应量周期（默认month）")

    parser.add_argument("--json", action="store_true", dest="output_json", help="输出JSON格式")

    args = parser.parse_args()

    if args.kline:
        if not args.start or not args.end:
            print("--kline 需要同时指定 --start 和 --end")
            sys.exit(1)
        cmd_kline(args.kline, args.start, args.end, args.freq, args.adjust, args.limit, args.output_json)
    elif args.basic:
        cmd_basic(args.basic, args.output_json)
    elif args.financials:
        if not args.start or not args.end:
            print("--financials 需要同时指定 --start 和 --end")
            sys.exit(1)
        cmd_financials(args.financials, args.start, args.end, args.output_json)
    elif args.profit:
        cmd_financial_single("profit", "盈利能力", args.profit, args.year, args.quarter, args.output_json)
    elif args.operation:
        cmd_financial_single("operation", "营运能力", args.operation, args.year, args.quarter, args.output_json)
    elif args.growth:
        cmd_financial_single("growth", "成长能力", args.growth, args.year, args.quarter, args.output_json)
    elif args.balance:
        cmd_financial_single("balance", "偿债能力", args.balance, args.year, args.quarter, args.output_json)
    elif args.cashflow:
        cmd_financial_single("cashflow", "现金流量", args.cashflow, args.year, args.quarter, args.output_json)
    elif args.dupont:
        cmd_financial_single("dupont", "杜邦分析", args.dupont, args.year, args.quarter, args.output_json)
    elif args.perf_express:
        if not args.start or not args.end:
            print("需要指定 --start 和 --end")
            sys.exit(1)
        cmd_performance("express", args.perf_express, args.start, args.end, args.output_json)
    elif args.perf_forecast:
        if not args.start or not args.end:
            print("需要指定 --start 和 --end")
            sys.exit(1)
        cmd_performance("forecast", args.perf_forecast, args.start, args.end, args.output_json)
    elif args.dividend:
        if not args.year:
            print("--dividend 需要指定 --year")
            sys.exit(1)
        cmd_dividend(args.dividend, args.year, args.output_json)
    elif args.industry:
        cmd_industry(args.code, args.output_json)
    elif args.hs300:
        cmd_index_members("hs300", args.date, args.output_json)
    elif args.sz50:
        cmd_index_members("sz50", args.date, args.output_json)
    elif args.zz500:
        cmd_index_members("zz500", args.date, args.output_json)
    elif args.trade_dates:
        cmd_trade_dates(args.start, args.end, args.output_json)
    elif args.deposit_rate:
        cmd_macro("deposit", args.start, args.end, args.period, args.output_json)
    elif args.loan_rate:
        cmd_macro("loan", args.start, args.end, args.period, args.output_json)
    elif args.reserve_ratio:
        cmd_macro("reserve", args.start, args.end, args.period, args.output_json)
    elif args.money_supply:
        cmd_macro("money", args.start, args.end, args.period, args.output_json)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
