---
name: a-share-skill
description: 查询A股实时行情、历史数据、技术指标、事件、资金面与个股行业信息。Use when 用户提到股票代码、板块、技术分析、财务指标、指数成分、交易日历、宏观数据或个股所属行业。
---

# A股数据综合分析

## 目标

使用本技能时，优先调用本目录下脚本获取结构化数据，不依赖网页抓取。

支持能力：
- 实时行情与市场维度
- 历史数据与财务维度
- 技术指标
- 个股事件
- 个股行业信息（`fetch_sector_info.py`，数据源东方财富；**不作为支持能力：概念板块**，见下）

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
python3 "$SKILL_DIR/scripts/fetch_sector_info.py" [参数]
```

说明：脚本虽可能带概念相关参数，但**上游概念接口结果不稳定、常为空**，本技能**不将概念查询列为可用能力**；使用时请固定加 `--no-concepts`，只查行业与证券简称。

## 代码格式约定

优先使用以下股票代码格式：
- 纯数字：`600519`
- 市场前缀：`sh600519` / `sz000001`
- JoinQuant：`600519.XSHG`

## 脚本路由规则

按问题类型选脚本：
- `fetch_realtime.py`：实时价格、分钟线、指数、北向、龙虎榜、涨跌停、板块、资金流、新闻、全市场行情、成交明细
- `fetch_history.py`：历史K线、财务、业绩、分红、行业、指数成分、交易日历、宏观
- `fetch_technical.py`：MA/MACD/KDJ/RSI/BOLL等技术指标
- `fetch_stock_events.py`：业绩、增减持/回购、监管、重大合同、舆情方向
- `fetch_sector_info.py`：单只或多只股票的行业与名称（东方财富）；批量时并行，默认 `--workers`；**仅文档化行业路径，不加概念**

## 执行流程

1. 先识别用户意图是实时、历史、技术、事件还是「个股所属行业」。
2. 选择对应脚本并优先加 `--json`。
3. 参数不足时补齐默认值后执行，不先空谈。
4. 返回时给出关键字段结论，并附可复现命令。

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
# 实时
python3 fetch_realtime.py --quote 600519 --json
python3 fetch_realtime.py --index --json
python3 fetch_realtime.py --boards-summary --boards-limit 20 --json
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

# 个股行业（不加概念，见上文说明）
python3 fetch_sector_info.py --no-concepts --json 600519
python3 fetch_sector_info.py --workers 8 --no-concepts --timeout 15 --json 600519 000001 300750 600036 601318 002594 688981 300059
```

## 不要做的事

- 不把本技能当成爬虫任务优先方案。
- 不在无必要时输出超长原始表格。
- 不使用已移除的旧流程文案。
- 不承诺或引导用户依赖 `fetch_sector_info.py` 的概念板块字段；技能侧只用 `--no-concepts` 的行业与名称结果。

## 参考

- 详细参数：`references/api-reference.md`
