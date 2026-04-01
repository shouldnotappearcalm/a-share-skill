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

### --market-news [--news-limit N] [--news-offset N]
市场新闻（DangInvest），数据源：DangInvest 开放接口。

接口：`https://dang-invest.com/api/market/news?limit=N&offset=M`

输出：
- 未加 `--json`：打印前若干条（最多 20 条）摘要，避免输出过长
- 加 `--json`：输出 `{"meta": {...}, "data": [...]}`，其中 `data` 内包含 `id/source/published_at/title/content/url` 等字段

---

### --boards-summary [--boards-mode industry] [--boards-limit N] [--boards-sort sortKey]
行业板块概览（DangInvest），接口：
`https://dang-invest.com/api/market/boards/summary?mode=industry&limit=N&sort=sortKey`

未加 `--json`：打印前若干条（最多 20 条）聚合摘要（`groupLabel / changePct / count / totalMarketCapYuan / totalTurnoverYuan`）  
加 `--json`：输出 `{"meta": {...}, "data": [...]}`（`data` 为 `items[]`）

### --boards-detail --boards-group-key KEY [--boards-mode industry] [--boards-sort sortKey] [--boards-items-limit N] [--boards-items-offset M]
行业板块成分明细（DangInvest），接口：
`https://dang-invest.com/api/market/boards/detail?mode=industry&groupKey=KEY&sort=sortKey&items_limit=N&items_offset=M`

未加 `--json`：打印板块汇总 + 前若干条成分（最多 20 条）  
加 `--json`：输出 `{"meta": {...}, "data": {...}}`（`data` 包含 `summary/items/itemsMeta`）

---

## fetch_history.py 参数详解

### --kline CODE --start YYYY-MM-DD --end YYYY-MM-DD

| 参数 | 默认值 | 说明 |
|---|---|---|
| --freq | d | 频率：d(日)/w(周)/m(月) |
| --limit | 500 | 最大返回行数（会映射到内部 count） |

返回字段（常见）：time / code / open / high / low / close / preclose / volume / pctChg

### --financials CODE --start YYYY-MM-DD --end YYYY-MM-DD

查询综合财务指标，数据源：akshare。

### 单项财务指标

`--profit` / `--growth` / `--balance` / `--cashflow` / `--dupont`

说明：单项维度与综合指标同源，按脚本内部统一口径输出。

### 业绩快报/预告

`--perf-express CODE`  
`--perf-forecast CODE`

### 全市场股票列表

`--all-stocks [--market sh|sz]`

说明：已支持新浪/腾讯/雪球三路聚合，自动去重；单源失败不影响整体返回。
JSON 输出结构：
- `meta.market`：市场范围
- `meta.total`：去重后总数
- `meta.sources`：各来源命中数量
- `data`：股票列表（`代码`/`名称`）

### 宏观经济数据

| 命令 | 内容 | 日期格式 |
|---|---|---|
| `--deposit-rate` | 存款基准利率 | 接口可用即返回 |
| `--loan-rate` | 贷款基准利率 | 接口可用即返回 |
| `--reserve-ratio` | 存款准备金率 | 接口可用即返回 |
| `--money-supply` | 货币供应量 | 接口可用即返回 |

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

## fetch_sector_info.py 参数详解

查询单只或多只股票的**证券简称与申万/东财行业分类**，数据源：**东方财富** HTTP 接口。

本参考与 `SKILL.md` 对齐：**不将「概念板块」列为可用能力**（上游概念接口结果不稳定、实践中常为空）。文档与技能用法上请**始终加 `--no-concepts`**，只使用行业与名称维度。

### 用法

- 单只：`python3 fetch_sector_info.py --no-concepts --json 600519`
- 多只（空格或逗号分隔，内部线程池并行）：`python3 fetch_sector_info.py --workers 8 --no-concepts --timeout 15 --json 600519 000001 300750`

| 参数 | 说明 |
|---|---|
| `codes` | 位置参数，一只或多只代码，支持空格或逗号分隔 |
| `--workers` | 并发线程数 |
| `--timeout` | 单只股票请求超时（秒） |
| `--no-concepts` | **技能侧必选**：跳过概念板块请求，仅行业+名称 |
| `--json` | 输出 JSON（多只时通常带 `data` 与耗时等元信息，以脚本实际输出为准） |
| `--batch-test` | 使用脚本内置列表做批量自检 |

返回字段（行业路径）：`code` / `name` / `industry` / `source`（一般为 `eastmoney`）等；`concepts` 即使存在也不作为本技能承诺字段。

---

## 常见股票代码

| 股票 | 代码 | 市场前缀格式 |
|---|---|---|
| 贵州茅台 | 600519 | sh600519 |
| 中国平安 | 601318 | sh601318 |
| 招商银行 | 600036 | sh600036 |
| 宁德时代 | 300750 | sz300750 |
| 比亚迪 | 002594 | sz002594 |
| 中芯国际 | 688981 | sh688981 |
| 平安银行 | 000001 | sz000001 |
| 万科A | 000002 | sz000002 |

## 大盘指数代码

| 指数 | 代码 | 说明 |
|---|---|---|
| 上证指数 | sh000001 | 沪市综合 |
| 深证成指 | sz399001 | 深市综合 |
| 创业板指 | sz399006 | 创业板 |
| 科创50 | sh000688 | 科创板 |
| 沪深300 | sh000300 | 两市核心 |
| 中证500 | sh000905 | 中小盘 |
