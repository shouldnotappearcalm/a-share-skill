---
name: a-share-strategy-mainboard-multi-swing-defensive
description: A 股主板流动性池内按趋势回踩（trend_pullback）产出买入候选与持仓卖出信号，供下单前决策；不跑回测、不自动下单。Use when 用户要选股、判断今日是否适合买/卖、或批量检查持仓是否触发策略离场条件。
---

# 主板多波段防御型 · 决策信号

本 skill 只做三件事：**选股范围**、**买入侧信号**、**卖出侧信号**。  
输出的是**决策参考**（结构化列表或 JSON），**不包含**历史回测撮合、**不包含**自动报单；真实下单请用券商或另接 `a-share-paper-trading` 等执行通道。

## 能力边界

| 做 | 不做 |
|----|------|
| 从主板高流动性股票中取前 N 只构成当日股票池 | 分钟级回测、混合回测、收益曲线 |
| 用日线 `trend_pullback` 标出入场/离场条件 | 保证收益或替代投顾 |
| 给出两类「买入参考」列表（见下） | 直接向交易所或模拟盘服务下单 |
| 可选：读取持仓列表文件，标出「策略离场」标的 | 替你保存实盘持仓（除非你自建文件） |

## 策略逻辑（与参数）

默认参数见 `scripts/strategy_lab/strategy_params.py`（均线快慢、回踩幅度、RSI 区间与离场 RSI 等）。  
信号计算在 `scripts/strategy_lab/strategies.py` 的 `trend_pullback`。

**买入参考（两组，请区分语义）：**

- **`from_previous_day_close`**：上一根已收盘日线满足 `entry`。与「前一日收盘后出信号、当日再执行」的习惯一致，**更贴近事前计划**。
- **`from_last_close`**：最新一根日线也满足 `entry`，偏**形态展示**；若与上一日重复，请避免重复计数。

列表内按策略内 **`score`（均线强弱）** 降序；默认**每种买入列表最多保留 5 只**（`strategy_params.MAX_BUY_CANDIDATES`），与「同时关注仓位不宜过多」一致。需要更多或全部时加 `--max-buys 0` 表示不截断，或 `--max-buys 10` 等。

**卖出参考：**  
对 `--holdings` 文件中的代码，若**最新一根日线**满足 `exit`（破慢线或 RSI 过高等规则内条件），则列入卖出参考。文件格式：一行一只代码，可含注释行（`#` 开头）。

**风控参考（仅文档与 JSON 字段）：**  
`REFERENCE_INTRADAY_STOP_PCT` 表示历史上与策略文档一致的**日内止损比例参考**，本脚本**不**替你监控盘中止损，需自行在下单软件中设置。

## 环境与依赖

```bash
pip install akshare pandas numpy requests
```

## 运行

```bash
SKILL_DIR="<本 skill 绝对路径>"
python3 "$SKILL_DIR/scripts/daily_decisions.py" --json
```

常用参数：

- `--top-n`：股票池大小，默认 120  
- `--max-buys`：买入侧列表在排序后最多保留几条，默认 5；传 `0` 不截断  
- `--holdings`：持仓代码文件路径  
- `--workers`：拉日线并发数  
- `--json`：输出一份 JSON，便于程序消费（JSON 内含截断前数量 `*_total`）  

示例：

```bash
python3 "$SKILL_DIR/scripts/daily_decisions.py" --top-n 120 --holdings "$HOME/my_holdings.txt"
```

## 脚本布局

| 路径 | 作用 |
|------|------|
| `scripts/daily_decisions.py` | 入口：拉池、算信号、打印或 `--json` |
| `scripts/paper_trading/market_data.py` | 行情与 `get_mainboard_universe` |
| `scripts/strategy_lab/strategies.py` | `trend_pullback` |
| `scripts/strategy_lab/indicators.py` | 均线、RSI |
| `scripts/strategy_lab/strategy_params.py` | 默认参数与策略名 |

## 与执行层衔接

若要将信号落到模拟盘，可在 Agent 中组合使用 **`a-share-paper-trading`**：先读本 skill 输出，再调用模拟盘 CLI 或 HTTP API 下单；本 skill **不**依赖模拟盘进程。
