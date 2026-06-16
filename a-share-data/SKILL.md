---
name: a-share-data
description: 查询A股实时行情、历史数据、技术指标、事件、资金面、热门行业/概念、板块热力图与个股行业信息。Use when 用户提到股票代码、板块、热门概念、热门行业、概念涨跌、行业涨跌、热力图、市场快讯、技术分析、财务指标、指数成分、交易日历、宏观数据或个股所属行业。
---

# A股数据综合分析

## 目标

使用本技能时，优先调用本目录下脚本获取结构化数据，不依赖网页抓取。

支持能力：
- 实时行情与市场维度
- 历史数据与财务维度
- 技术指标
- 个股事件
- A+H 双重上市公司列表（支持按 H 股上市日期筛选）
- A股赴港上市关键事件时间节点（递表/聆讯/备案/招股/定价/配售/上市）
- 热门行业、热门概念、行业/概念涨跌幅、板块热力图、板块成分股、7×24 市场快讯（`fetch_danginvest.py`；**先读** `references/danginvest-api-reference.md`）
- 个股行业信息（`fetch_sector_info.py`，数据源东方财富；**个股概念**不稳定，见下）

## 环境与路径

```bash
pip install akshare MyTT pandas numpy requests
```

```bash
SKILL_DIR="<本skill绝对路径>"
python3 "$SKILL_DIR/scripts/fetch_realtime.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_history.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_technical.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_stock_events.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_ah_stocks.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_ah_ipo_timeline.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_danginvest.py" [参数]
python3 "$SKILL_DIR/scripts/fetch_sector_info.py" [参数]
```

说明：`fetch_sector_info.py` 虽可能带概念参数，但东方财富**个股概念**接口不稳定、常为空，使用时固定加 `--no-concepts`，只查行业与证券简称。**市场级概念板块**（涨跌幅、热力图、成分股）走 `fetch_danginvest.py`，不要与前者混用。

## 代码格式约定

优先使用以下股票代码格式：
- 纯数字：`600519`
- 市场前缀：`sh600519` / `sz000001`
- JoinQuant：`600519.XSHG`

## 脚本路由规则

按问题类型选脚本：
- `fetch_danginvest.py`：**热门概念、热门行业、行业涨跌幅、概念涨跌幅**、板块热力图、板块成分股、7×24 市场快讯；参数与查询惯例见 `references/danginvest-api-reference.md`
- `fetch_realtime.py`：实时价格、分钟线、指数、北向、龙虎榜、涨跌停、资金流、全市场行情、成交明细（`--boards-*` 仅兼容旧用法）
- `fetch_history.py`：历史K线、财务、业绩、分红、行业、指数成分、交易日历、宏观
- `fetch_technical.py`：MA/MACD/KDJ/RSI/BOLL等技术指标
- `fetch_stock_events.py`：业绩、增减持/回购、监管、重大合同、舆情方向
- `fetch_ah_stocks.py`：A+H 双重上市公司清单、H 股上市日期区间筛选
- `fetch_ah_ipo_timeline.py`：A股赴港上市关键事件节点（递表/聆讯/备案/招股/定价/配售/上市）；支持 `--code` / `--name` 点查
- `fetch_sector_info.py`：单只或多只股票的行业与名称（东方财富）；批量时并行，默认 `--workers`；**仅文档化行业路径，不加概念**

## 执行流程

1. 先识别用户意图：实时、历史、技术、事件、A股赴港上市时间节点、**热门行业/热门概念/行业或概念涨跌幅**、板块热力图、7×24 快讯，或「个股所属行业」。
2. 命中下列任一表述时，**先读** `references/danginvest-api-reference.md`，再用 `fetch_danginvest.py`（勿用 `fetch_realtime.py --boards-*`）：
   - 今天/今日**热门概念**、什么概念涨得多、概念领涨/领跌
   - 今天/今日**热门行业**、什么行业涨得多、行业领涨/领跌（含大类行业、细分行业）
   - **行业涨跌幅**、**概念涨跌幅**、板块热力图、某板块成分股
   - 7×24 市场快讯
3. 选择对应脚本并优先加 `--json`。
4. 参数不足时补齐默认值后执行，不先空谈。
5. 返回时给出关键字段结论，并附可复现命令。

## 降级与容错规则

- 历史能力统一走 `fetch_history.py`（已内置多源逻辑，K线链路为腾讯优先、新浪降级、东财兜底）。
- 遇到上游限流或临时失败：
  - 同类接口先重试 1-2 次。
  - 可降级就降级，不能降级则明确标注为“上游数据源不可用”。
- `--all-stocks` 已支持新浪/腾讯/雪球多源；若单一源失败，继续返回其他源合并结果。

## 批量数据并行与超时规范（强制）

当任务是“批量拉取”时（实时个股列表 / 多只历史K线），默认并行，不逐只串行。

- 推荐并发：`max_workers=8~12`（默认 10）
- 每只股票独立异常捕获，失败不阻断整批
- 结果输出必须包含：样本数、成功率、总耗时、失败代码清单

超时上限（硬限制）：
- **批量实时个股列表**：整批任务最多等待 `30s`
- **批量历史K线（多只）**：整批任务最多等待 `30s`
- **全市场并发任务**：整批任务最多等待 `60s`

超时/失败处理（强制）：
- 到达超时即停止等待并返回当前结果
- 失败就标记失败，不做长时间阻塞重试
- 禁止无上限重试或“卡住一直等”

## 输出规范

- 默认返回结构化要点，不堆长表。
- 需要原始数据时再返回完整 JSON。
- 明确数据源与时间点（如交易日、更新时间、盘中/休市状态）。

## 常用命令最小集

```bash
# 实时（单只）
python3 fetch_realtime.py --quote 600519 --json
# 实时（多只，逗号分隔，最多10只）
python3 fetch_realtime.py --multi-quote 002491,002364,600519 --json
python3 fetch_realtime.py --index --json
python3 fetch_realtime.py --all-quote --sort change_pct_desc --top 50 --json
python3 fetch_realtime.py --tick 600519 --json

# 历史
python3 fetch_history.py --kline 600519 --start 2025-01-01 --end 2025-03-31 --freq d --json
python3 fetch_history.py --kline-batch 600519,000001,300750 --start 2025-10-01 --end 2026-03-31 --count 120 --workers 8 --retries 2 --json
python3 fetch_history.py --financials 600519 --start 2023-01-01 --end 2025-01-01 --json
python3 fetch_history.py --industry 300271 --with-boards --json

# 技术
python3 fetch_technical.py 600519 --freq 1d --count 120 --indicators MA,MACD,KDJ,RSI,BOLL --json

# 事件
python3 fetch_stock_events.py --code 300476 --name 胜宏科技 --dates 20250331,20241231 --limit 20 --json

# A+H 列表
python3 fetch_ah_stocks.py --json
python3 fetch_ah_stocks.py --since 2020-01-01 --until 2024-12-31 --json

# A股赴港上市关键节点
python3 fetch_ah_ipo_timeline.py --name 顺丰 --json
python3 fetch_ah_ipo_timeline.py --code 002352 --json
python3 fetch_ah_ipo_timeline.py --since 2020 --workers 4 --json

# 热门行业/热门概念/涨跌幅/快讯 → fetch_danginvest.py，见 references/danginvest-api-reference.md

# 个股行业（不加概念，见上文说明）
python3 fetch_sector_info.py --no-concepts --json 600519
python3 fetch_sector_info.py --workers 8 --no-concepts --timeout 15 --json 600519 000001 300750 600036 601318 002594 688981 300059
```

## 不要做的事

- 不把本技能当成爬虫任务优先方案。
- 不在无必要时输出超长原始表格。
- 不使用已移除的旧流程文案。
- 热门概念、热门行业、行业/概念涨跌幅、板块热力图、板块成分、市场快讯：用 `fetch_danginvest.py`，**先读** `references/danginvest-api-reference.md`；勿用 `fetch_realtime.py --boards-*`。
- 不承诺 `fetch_sector_info.py` 的个股概念字段；市场级「热门概念/概念涨跌」走 `fetch_danginvest.py`，不是 sector_info。

## 参考

- 实时/历史/技术等脚本参数：`references/api-reference.md`
- **热门行业、热门概念、行业/概念涨跌幅、热力图、成分股、快讯**（触发词、默认查哪些维度、命令示例）：`references/danginvest-api-reference.md`
- GitHub 项目地址：[https://github.com/shouldnotappearcalm/a-share-skill](https://github.com/shouldnotappearcalm/a-share-skill)
