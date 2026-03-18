---
name: a-share-skill
description: A股市场全场景数据分析技能。支持实时行情快照（分钟K线聚合+市场状态）、今日分钟K线、批量行情、分钟/日/周K线、
  MACD/KDJ/RSI/BOLL等12种技术指标、盈利/成长/偿债/现金流/杜邦六维财务报表、热点概念板块、北向资金、龙虎榜、
  涨停板/连板股、个股资金流向、沪深300/上证50/中证500指数成分股、存款利率/货币供应量等宏观数据。
  数据源覆盖东方财富、新浪财经、腾讯财经、Baostock。
  Use when: 用户查询A股行情、个股分析、技术指标、财务报表、热点板块、资金面数据、宏观经济数据，或需要精准的历史数据支撑分析。
---

# A股数据综合分析工具

## 角色定位

本 skill 提供 A 股市场全场景数据查询，优先于直接爬取网页。数据来源：
- **实时数据**：腾讯/新浪直接 API（K线聚合方式，无需第三方 Ashare 库）+ 东方财富（通过 akshare）
- **历史数据**：Baostock（当日 17:30 后更新）
- **技术指标**：腾讯/新浪实时K线 + MyTT 计算

## 环境安装

```bash
pip install akshare MyTT baostock pandas numpy requests
```

## 脚本路径

所有脚本位于本 skill 目录下的 `scripts/` 文件夹。调用时使用绝对路径：

```bash
SKILL_DIR="<本skill的绝对路径>"
python3 "$SKILL_DIR/scripts/fetch_realtime.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_history.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_technical.py" [参数]
```

## 股票代码格式

三个脚本均自动识别多种格式：

| 输入格式 | 示例 | 说明 |
|---|---|---|
| 纯数字 | `600519` | 自动判断市场（6开头→上海，0/3→深圳） |
| Baostock | `sh.600519` | 历史数据推荐格式 |
| 通达信 | `sh600519` | 均支持 |
| JoinQuant | `600519.XSHG` | 均支持 |

---

## 脚本一：fetch_realtime.py（实时行情）

**依赖**：akshare + requests（无需 ashares 库，直接调用腾讯/新浪 API）

```bash
# 实时行情快照（分钟K线聚合方式：昨收+5m聚合今日OHLCV，含市场状态）
python3 fetch_realtime.py --quote 600519

# 今日分钟K线（只返回今日数据）
python3 fetch_realtime.py --intraday-kline 600519 --freq 5m
python3 fetch_realtime.py --intraday-kline 000001 --freq 1m

# 批量实时行情（最多10只，按涨跌幅排序）
python3 fetch_realtime.py --multi-quote 600519,000001,300750

# K线数据（历史+实时连续）
python3 fetch_realtime.py --kline 600519 --freq 1d --count 60
python3 fetch_realtime.py --kline 000001 --freq 5m --count 30

# 四大指数（上证/深证/创业板/科创50）
python3 fetch_realtime.py --index

# 热点概念板块 TOP20
python3 fetch_realtime.py --hot-sectors --top 20

# 北向资金
python3 fetch_realtime.py --north-money

# 龙虎榜（默认近3日；当日数据未发布时给出友好提示）
python3 fetch_realtime.py --lhb --start 20260310 --end 20260318 --top 20

# 涨跌停统计
python3 fetch_realtime.py --limit-stats

# 涨停股池
python3 fetch_realtime.py --limit-up-pool --date 20260318 --top 30

# 个股资金流向（近10日主力/大单/中单/小单净额）
python3 fetch_realtime.py --fund-flow 600519 --days 10

# 连板股（昨日连板今日表现）
python3 fetch_realtime.py --consecutive-limit

# 输出 JSON
python3 fetch_realtime.py --quote 600519 --json
```

**K线频率参数**：`1m` / `5m` / `15m` / `30m` / `60m` / `1d`（默认）/ `1w` / `1M`

**市场状态说明**（`--quote` 输出字段）：
- `交易中`：当前在交易时段（9:30-11:30 / 13:00-15:00）
- `盘前` / `盘后`：盘前（9:00-9:30）或盘后（15:00 后）
- `休市`：非交易日或节假日

---

## 脚本二：fetch_history.py（历史与财务）

**依赖**：baostock  
**注意**：当日数据在 17:30 后入库，分钟线在次日 11:00 入库

```bash
# 历史K线（默认不复权，adjust=2 为前复权）
python3 fetch_history.py --kline 600519 --start 2025-01-01 --end 2026-03-18
python3 fetch_history.py --kline 600519 --start 2024-01-01 --end 2026-01-01 --adjust 2 --freq d

# 股票基本信息（名称/行业/上市日期）
python3 fetch_history.py --basic sh.600519

# 综合财务指标（盈利/营运/成长/偿债/现金流/杜邦，一次全取）
python3 fetch_history.py --financials sh.600519 --start 2023-01-01 --end 2026-01-01

# 单项财务数据（按季度）
python3 fetch_history.py --profit sh.600519 --year 2024 --quarter 4
python3 fetch_history.py --growth sh.600519 --year 2024 --quarter 4
python3 fetch_history.py --balance sh.600519 --year 2024 --quarter 4
python3 fetch_history.py --cashflow sh.600519 --year 2024 --quarter 4
python3 fetch_history.py --dupont sh.600519 --year 2024 --quarter 4

# 业绩快报 / 业绩预告
python3 fetch_history.py --perf-express sh.600519 --start 2024-01-01 --end 2026-01-01
python3 fetch_history.py --perf-forecast sh.600519 --start 2024-01-01 --end 2026-01-01

# 分红配送
python3 fetch_history.py --dividend sh.600519 --year 2024

# 行业分类
python3 fetch_history.py --industry --code sh.600519
python3 fetch_history.py --industry  # 全市场行业列表

# 指数成分股
python3 fetch_history.py --hs300           # 沪深300
python3 fetch_history.py --sz50            # 上证50
python3 fetch_history.py --zz500           # 中证500
python3 fetch_history.py --hs300 --date 2025-12-31  # 历史成分

# 交易日历
python3 fetch_history.py --trade-dates --start 2026-03-01 --end 2026-03-31

# 宏观经济数据
python3 fetch_history.py --deposit-rate    # 存款基准利率
python3 fetch_history.py --loan-rate       # 贷款基准利率
python3 fetch_history.py --reserve-ratio   # 存款准备金率
python3 fetch_history.py --money-supply --period month  # 月度货币供应量(M0/M1/M2)
python3 fetch_history.py --money-supply --period year   # 年度货币供应量
```

**K线频率**：`d`（日，默认）/ `w`（周）/ `m`（月）/ `5` / `15` / `30` / `60`（分钟）  
**复权参数**：`1`（后复权）/ `2`（前复权）/ `3`（不复权，默认）

---

## 脚本三：fetch_technical.py（技术指标）

**依赖**：MyTT + requests（直接调用腾讯/新浪 API，无需 ashares 库）  
**特点**：使用实时K线数据计算指标，盘中可用，自动输出信号解读

```bash
# 默认指标：MA + MACD + KDJ + RSI + BOLL
python3 fetch_technical.py 600519

# 自定义频率和指标
python3 fetch_technical.py 000001 --freq 1d --count 120 --indicators MA,MACD,KDJ,RSI,BOLL

# 分钟线技术分析
python3 fetch_technical.py 300750 --freq 15m --count 60 --indicators MACD,KDJ,BOLL

# 输出 JSON（不含信号解读）
python3 fetch_technical.py 600519 --json
```

**可用指标**：

| 指标 | 说明 | 输出字段 |
|---|---|---|
| `MA` | 移动平均线 | MA5/MA10/MA20/MA60 |
| `EMA` | 指数移动平均 | EMA12/EMA26 |
| `MACD` | MACD | MACD_DIF/MACD_DEA/MACD |
| `KDJ` | 随机指标 | KDJ_K/KDJ_D/KDJ_J |
| `RSI` | 相对强弱 | RSI |
| `WR` | 威廉指标 | WR10/WR6 |
| `BOLL` | 布林带 | BOLL_UP/BOLL_MID/BOLL_LOW |
| `BIAS` | 乖离率 | BIAS6/BIAS12/BIAS24 |
| `CCI` | 商品通道 | CCI |
| `ATR` | 真实波幅 | ATR |
| `DMI` | 趋向指标 | DMI_PDI/DMI_MDI/DMI_ADX/DMI_ADXR |
| `TAQ` | 唐安奇通道 | TAQ_UP/TAQ_MID/TAQ_DOWN |

---

## 常用工作流

### 1. 个股综合分析

```bash
# Step 1：实时行情
python3 fetch_realtime.py --quote 600519

# Step 2：技术指标（日线，默认指标）
python3 fetch_technical.py 600519 --count 120

# Step 3：基本面（近2年综合财务指标）
python3 fetch_history.py --financials sh.600519 --start 2024-01-01 --end 2026-01-01
```

### 2. 大盘情绪判断

```bash
python3 fetch_realtime.py --index
python3 fetch_realtime.py --limit-stats
python3 fetch_realtime.py --hot-sectors
python3 fetch_realtime.py --north-money
```

### 3. 涨停板分析

```bash
python3 fetch_realtime.py --limit-up-pool
python3 fetch_realtime.py --consecutive-limit
python3 fetch_realtime.py --lhb
```

### 4. 历史回测数据准备

```bash
# 前复权日K线
python3 fetch_history.py --kline sh.600519 --start 2020-01-01 --end 2026-01-01 --adjust 2

# 同期财务指标
python3 fetch_history.py --financials sh.600519 --start 2020-01-01 --end 2026-01-01
```

---

## 数据时效说明

| 数据类型 | 脚本 | 更新时间 |
|---|---|---|
| 实时行情/大盘指数 | fetch_realtime.py | 交易时间内实时 |
| 实时K线（含分钟线） | fetch_realtime.py --kline | 盘中即时 |
| 热点板块/北向资金/龙虎榜 | fetch_realtime.py | 盘中/T+1 |
| 历史日K线 | fetch_history.py --kline | 当日 17:30 后 |
| 分钟K线（历史） | fetch_history.py --kline --freq 15 | 次日 11:00 |
| 财务报表 | fetch_history.py --financials | 季报发布后 |
| 指数成分 | fetch_history.py --hs300 等 | 每周一更新 |

## 参考资料

详细参数说明见 [references/api-reference.md](references/api-reference.md)
