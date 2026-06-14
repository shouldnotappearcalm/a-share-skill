# a-share-data AI 使用流程

这份文档说明如何把 `a-share-data` 配到常见 AI 工具里使用，并给出安装、依赖、自检、提问方式和典型使用案例。

适用场景：

- 想让 AI 查询 A 股实时行情、历史数据、技术指标、资金面、事件和行业信息
- 想在 `Codex / Cursor / Claude Code / OpenCode / openclaw` 里直接调用这个 skill
- 想先得到结构化数据，再让 AI 做分析

## 这个 skill 做什么

`a-share-data` 是仓库里的综合数据 skill，主要负责：

- 实时行情与分钟线
- 历史 K 线与财务数据
- 技术指标
- 个股事件
- A+H 双重上市清单
- A 股赴港上市关键时间节点
- 个股行业信息

它更适合做：

- 单只股票综合分析
- 多只股票批量拉数
- 盘中热点与市场状态跟踪
- 给其他策略或模拟盘提供行情输入

## 安装到 AI 工具

以下命令都在仓库根目录执行。

### Codex

```bash
mkdir -p ~/.agents/skills
cp -R a-share-data ~/.agents/skills/
```

### Cursor

```bash
mkdir -p ~/.cursor/skills
cp -R a-share-data ~/.cursor/skills/
```

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -R a-share-data ~/.claude/skills/
```

### OpenCode

```bash
mkdir -p ~/.opencode/skills
cp -R a-share-data ~/.opencode/skills/
```

### openclaw

```bash
mkdir -p ~/.openclaw/workspace/skills
cp -R a-share-data ~/.openclaw/workspace/skills/
```

## AI 工具里怎么问

建议在提问时直接点名 `a-share-data`。

### 最常用问法

- `用 a-share-data 查 600519 最新行情，给我 json`
- `用 a-share-data 拉 600519 最近 60 个交易日日线`
- `用 a-share-data 计算 600519 的 MA、MACD、RSI`
- `用 a-share-data 看今天大盘指数和热点板块`
- `用 a-share-data 查 300476 最近的重要事件`

### 带参数的问法

- `用 a-share-data 拉 600519 从 2025-01-01 到 2025-03-31 的日线，json 输出`
- `用 a-share-data 批量拉 600519、000001、300750 最近 120 根日线`
- `用 a-share-data 查 600519 财务指标和行业信息`
- `用 a-share-data 看沪深300成分股`
- `用 a-share-data 查顺丰的赴港上市时间线`

## AI 背后实际会跑什么

不同需求会落到不同脚本：

- `fetch_realtime.py`: 实时行情、批量实时、指数、板块、资金流、新闻
- `fetch_history.py`: 历史 K 线、财务、分红、业绩、行业、指数成分、宏观
- `fetch_technical.py`: 技术指标
- `fetch_stock_events.py`: 个股事件
- `fetch_ah_stocks.py`: A+H 清单
- `fetch_ah_ipo_timeline.py`: A 股赴港上市关键节点
- `fetch_sector_info.py`: 行业与证券简称

## 常用命令

```bash
SKILL_DIR="$(pwd)/a-share-data"

# 实时
python3 "$SKILL_DIR/scripts/fetch_realtime.py" --quote 600519 --json
python3 "$SKILL_DIR/scripts/fetch_realtime.py" --multi-quote 002491,002364,600519 --json
python3 "$SKILL_DIR/scripts/fetch_realtime.py" --index --json
python3 "$SKILL_DIR/scripts/fetch_realtime.py" --boards-summary --boards-limit 20 --json

# 历史
python3 "$SKILL_DIR/scripts/fetch_history.py" --kline 600519 --start 2025-01-01 --end 2025-03-31 --freq d --json
python3 "$SKILL_DIR/scripts/fetch_history.py" --kline-batch 600519,000001,300750 --count 120 --workers 8 --json
python3 "$SKILL_DIR/scripts/fetch_history.py" --financials 600519 --json
python3 "$SKILL_DIR/scripts/fetch_history.py" --industry 300271 --with-boards --json

# 技术
python3 "$SKILL_DIR/scripts/fetch_technical.py" 600519 --freq 1d --count 120 --indicators MA,MACD,KDJ,RSI,BOLL --json

# 事件
python3 "$SKILL_DIR/scripts/fetch_stock_events.py" --code 300476 --name 胜宏科技 --dates 20250331,20241231 --limit 20 --json

# A+H / 赴港时间线
python3 "$SKILL_DIR/scripts/fetch_ah_stocks.py" --json
python3 "$SKILL_DIR/scripts/fetch_ah_ipo_timeline.py" --name 顺丰 --json

# 行业
python3 "$SKILL_DIR/scripts/fetch_sector_info.py" --no-concepts --json 600519
```

## 使用案例

### 案例 1：让 AI 做单只股票综合分析

可以这样问：

- `用 a-share-data 拉 600519 的最新行情、最近 60 日日线、MA/MACD/RSI，再给我一个高层结论`

适合场景：

- 看趋势
- 看量价
- 先拿数据，再让 AI 给结论

### 案例 2：盘中看指数和热点

可以这样问：

- `用 a-share-data 看当前指数、热点板块、北向资金，帮我判断今天市场强弱`

适合场景：

- 开盘后快速看市场状态
- 盘中判断是否值得继续做交易计划

### 案例 3：批量比较几只票

可以这样问：

- `用 a-share-data 批量拉 600519、000001、300750 最近 120 根日线和 MACD，帮我比较谁更强`

适合场景：

- 候选池比较
- 同行业强弱排序

### 案例 4：查事件驱动

可以这样问：

- `用 a-share-data 查 300476 最近的重要事件，按时间线列出来`

适合场景：

- 事件驱动复盘
- 个股异动背景核查

## 注意事项

- `fetch_sector_info.py` 的概念板块结果不稳定，建议固定使用 `--no-concepts`
- 批量任务已经内置并发和超时控制，但上游源异常时仍可能出现部分失败
- `--json` 更适合交给 AI 二次分析

## 与其他 skill 的关系

- `a-share-data`: 数据层
- `a-share-strategy-mainboard-multi-swing-defensive`: 信号层
- `a-share-paper-trading`: 执行层

典型链路是：

1. 用 `a-share-data` 拉数据
2. 用策略 skill 出信号
3. 用模拟盘 skill 执行
