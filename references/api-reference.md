# A股数据 API 完整参考

## fetch_realtime.py 参数详解

### --quote CODE
实时行情快照，数据源：东方财富。

返回字段：代码 / 名称 / 最新价 / 涨跌额 / 涨跌幅(%) / 今开 / 最高 / 最低 / 昨收 / 成交量(手) / 成交额(亿) / 换手率(%)

### --kline CODE
实时K线，数据源：Ashare（腾讯/新浪双核心）。

| 参数 | 默认值 | 说明 |
|---|---|---|
| --freq | 1d | 频率：1m/5m/15m/30m/60m/1d/1w/1M |
| --count | 60 | 返回K线条数 |

返回字段：时间 / 开盘 / 收盘 / 最高 / 最低 / 成交量

### --index
四大指数实时数据，数据源：新浪财经（通过 akshare）。

返回：上证指数(000001) / 上证A股(000002) / 深证成指(399001) / 创业板指(399006) / 科创50(000688)

### --hot-sectors [--top N]
概念板块涨幅榜，数据源：东方财富（通过 akshare）。

返回字段：排名 / 板块名称 / 涨跌幅(%) / 换手率(%) / 总市值(亿)

### --north-money
北向资金（沪深港通），数据源：东方财富（通过 akshare）。

返回字段：日期 / 板块 / 净买额(亿) / 净流入(亿) / 指数涨跌(%)

### --lhb [--start YYYYMMDD] [--end YYYYMMDD] [--top N]
龙虎榜，数据源：东方财富（通过 akshare）。默认近3日。

返回字段：代码 / 名称 / 上榜日 / 收盘价 / 涨跌幅(%) / 净买额(万) / 上榜原因

### --limit-stats
当日涨跌停数量统计，数据源：东方财富。

### --limit-up-pool [--date YYYYMMDD] [--top N]
涨停股池，数据源：东方财富。默认今日。

返回字段：序号 / 代码 / 名称 / 涨跌幅 / 最新价 / 成交额(亿) / 换手率 / 封板资金 / 连板数 / 所属行业

### --fund-flow CODE [--days N]
个股资金流向（近N日），数据源：东方财富。单位：万元。

返回字段：日期 / 收盘价 / 涨跌幅(%) / 主力净额(万) / 主力占比(%) / 超大单净额(万) / 大单净额(万) / 中单净额(万) / 小单净额(万)

### --consecutive-limit [--date YYYYMMDD] [--top N]
连板股（昨日连板今日表现），数据源：东方财富。

---

## fetch_history.py 参数详解

### --kline CODE --start YYYY-MM-DD --end YYYY-MM-DD

| 参数 | 默认值 | 说明 |
|---|---|---|
| --freq | d | 频率：d(日)/w(周)/m(月)/5/15/30/60(分钟) |
| --adjust | 3 | 复权：1(后复权)/2(前复权)/3(不复权) |
| --limit | 500 | 最大返回行数 |

返回字段（日线）：date / code / open / high / low / close / preclose / volume / amount / pctChg / turn / peTTM / pbMRQ

### --financials CODE --start YYYY-MM-DD --end YYYY-MM-DD

一次查询并合并以下6类季度财务指标：

**盈利能力（profit_）**：roeAvg / npMargin / gpMargin / netProfit / epsTTM / MBRevenue / totalShare / liqaShare

**营运能力（operation_）**：NRTurnRatio / NRTurnDays / INVTurnRatio / INVTurnDays / CATurnRatio / AssetTurnRatio

**成长能力（growth_）**：YOYEquity / YOYAsset / YOYNI / YOYEPSBasic / YOYNIDeducted

**偿债能力（balance_）**：currentRatio / quickRatio / cashRatio / YOYLiability / liabilityToAsset / assetToEquity

**现金流量（cashflow_）**：CAToAsset / NCAToAsset / tangibleAssetToAsset / ebitToInterest / CFOToOR / CFOToNP

**杜邦分析（dupont_）**：dupontROE / dupontAssetTurn / dupontPnitoni / dupontNitogr / dupontEquityMul

### 单项财务指标

`--profit` / `--operation` / `--growth` / `--balance` / `--cashflow` / `--dupont`

参数：`--year YYYY` + `--quarter 1|2|3|4`

### 业绩快报/预告

`--perf-express CODE --start YYYY-MM-DD --end YYYY-MM-DD`  
`--perf-forecast CODE --start YYYY-MM-DD --end YYYY-MM-DD`

### 宏观经济数据

| 命令 | 内容 | 日期格式 |
|---|---|---|
| `--deposit-rate` | 存款基准利率 | YYYY-MM-DD |
| `--loan-rate` | 贷款基准利率 | YYYY-MM-DD |
| `--reserve-ratio` | 存款准备金率 | YYYY-MM-DD |
| `--money-supply --period month` | 月度货币供应(M0/M1/M2) | YYYY-MM |
| `--money-supply --period year` | 年度货币供应 | YYYY |

---

## fetch_technical.py 参数详解

```
CODE        股票代码（必填）
--freq      K线频率（默认 1d）
--count     K线条数（默认 120，建议 >=120 确保指标准确）
--indicators 指标列表，逗号分隔（默认 MA,MACD,KDJ,RSI,BOLL）
--no-signal  不输出信号解读文字
--json       输出 JSON 格式
```

### 指标计算参数说明

| 指标 | 参数 | 说明 |
|---|---|---|
| MA | 5/10/20/60日 | 简单移动平均 |
| EMA | 12/26日 | 指数移动平均 |
| MACD | 12/26/9 | DIF=EMA12-EMA26; DEA=EMA(DIF,9); MACD=2*(DIF-DEA) |
| KDJ | 9/3/3 | RSV=最高最低9日; K=2/3K+1/3RSV; D=2/3D+1/3K; J=3K-2D |
| RSI | 24日 | 相对强弱指标，>80超买，<20超卖 |
| WR | 10/6日 | 威廉指标 |
| BOLL | 20/2 | 中轨MA20，上下轨=MA20±2σ |
| BIAS | 6/12/24日 | 乖离率=(收盘-MAn)/MAn×100 |
| CCI | 14日 | 商品通道指数 |
| ATR | 20日 | 真实波幅，衡量波动性 |
| DMI | 14/6日 | 方向运动指标（PDI/MDI/ADX） |
| TAQ | 20日 | 唐安奇通道（上轨/中轨/下轨） |

---

## 常见股票代码

| 股票 | 代码 | Baostock格式 |
|---|---|---|
| 贵州茅台 | 600519 | sh.600519 |
| 中国平安 | 601318 | sh.601318 |
| 招商银行 | 600036 | sh.600036 |
| 宁德时代 | 300750 | sz.300750 |
| 比亚迪 | 002594 | sz.002594 |
| 中芯国际 | 688981 | sh.688981 |
| 平安银行 | 000001 | sz.000001 |
| 万科A | 000002 | sz.000002 |

## 大盘指数代码

| 指数 | 代码 | 说明 |
|---|---|---|
| 上证指数 | sh000001 | 沪市综合 |
| 深证成指 | sz399001 | 深市综合 |
| 创业板指 | sz399006 | 创业板 |
| 科创50 | sh000688 | 科创板 |
| 沪深300 | sh000300 | 两市核心 |
| 中证500 | sh000905 | 中小盘 |
