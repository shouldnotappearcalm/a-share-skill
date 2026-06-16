---
name: tuige-shortline-trading
description: 基于退哥短线交易规则的A股场景化决策技能。Use when 用户要按交易场景查看短线规则、做选股、判断趋势回踩、涨停回调、连板接力、洗盘结束、卖出失效或仓位纪律。
---

# Tuige Shortline Trading

## 适用范围

这个 skill 用来把退哥体系中的短线规则整理成可复用的决策框架，重点回答 4 类问题：

- 当前市场环境适合做什么
- 哪些股票值得进入观察和候选池
- 不同交易场景下的触发条件与失效条件
- 仓位、纪律、退出规则如何统一约束

## 能力边界

- 输出的是决策参考，不是收益承诺
- 优先使用结构化规则，不直接复述口号
- 不自动下单，不替代回测，不代替投顾
- 遇到模糊概念时先回到 `glossary.md`

## 推荐使用顺序

1. 先读 [market-regime.md](api-reference/market-regime.md)
2. 再读 [stock-selection.md](api-reference/stock-selection.md)
3. 根据场景进入以下文档：
   - [trend-setups.md](api-reference/trend-setups.md)
   - [limit-up-pullback-setups.md](api-reference/limit-up-pullback-setups.md)
   - [relay-setups.md](api-reference/relay-setups.md)
   - [washout-breakout-setups.md](api-reference/washout-breakout-setups.md)
4. 最后用 [exit-failure-rules.md](api-reference/exit-failure-rules.md) 和 [position-discipline.md](api-reference/position-discipline.md) 复核
5. 如需统一术语，查 [glossary.md](api-reference/glossary.md)

## 场景地图

- `api-reference/market-regime.md`
  - 先判断今天是否允许激进短线、仅允许回调确认，还是应该空仓
- `api-reference/stock-selection.md`
  - 统一股票池构建、强势股筛选、回避规则
- `api-reference/trend-setups.md`
  - 处理趋势延续、回踩均线、缩量整理后的再起
- `api-reference/limit-up-pullback-setups.md`
  - 处理涨停后整理结构，例如三阴不破阳、揉搓线、缩倍量回调
- `api-reference/relay-setups.md`
  - 处理一进二、二进三、2+2 这类高风险接力
- `api-reference/washout-breakout-setups.md`
  - 处理黄金坑、假跌破、极度缩量后放量突破等洗盘末端确认
- `api-reference/exit-failure-rules.md`
  - 统一止盈兑现、趋势失效、结构失败、风险离场
- `api-reference/position-discipline.md`
  - 统一仓位等级、试错纪律、降频规则

## 标准输出模板

输出时统一包含以下结构：

1. 当前市场环境
2. 今日允许使用的场景模块
3. 候选池分级
4. 当前结构类型
5. 触发条件
6. 失效条件
7. 卖出观察点
8. 仓位建议
9. 明确回避原因

单只标的建议使用以下字段组织：

- 标的
- 所属题材
- 当前结构
- 入场依据
- trigger
- invalidation
- 卖出参考
- risk
- position_grade

## 使用约束

- 所有结论尽量写成“条件 / 风险 / 失效”
- 没有触发，不算买点
- 市场环境是总开关，环境不支持时不强行升级结论
- 同一只标的若同时命中多个场景，优先保留风险更低、定义更清晰的场景解释

## 工程化转换

当前目录已提供可执行脚本，结构与 `a-share-strategy-mainboard-multi-swing-defensive` 对齐：

- `scripts/daily_decisions.py`
  - 主板流动性池扫描 + `trend_pullback` 信号
  - 输出两类买入参考：`from_previous_day_close` 与 `from_last_close`
  - 支持持仓文件卖出信号检查
  - 默认最大持仓上限 `8`（可通过 `--max-holdings` 下调）
- `scripts/realtime_quotes.py`
  - 对指定代码批量拉取现价快照
- `scripts/strategy_lab/strategy_params.py`
  - 参数与仓位上限配置
- `scripts/strategy_lab/strategies.py`
  - 规则引擎核心（当前版本：趋势回踩 + RSI 区间 + 失效退出）

### 运行

```bash
SKILL_DIR="<本 skill 绝对路径>"
python3 "$SKILL_DIR/scripts/daily_decisions.py" --json
```

常用参数：

- `--top-n`：股票池大小，默认 120
- `--max-holdings`：最大持仓上限，默认 8
- `--max-buys`：买入输出上限，默认 8（最终会再受 `max-holdings` 约束）
- `--holdings`：持仓文件路径，一行一个代码
- `--roundtrip-cost-bps`：成本过滤，默认 45
- `--entry-consensus-min`：鲁棒一致性阈值，默认 0.67
- `--disable-robust-check`：关闭鲁棒性检查（仅调试）

### 说明

- 当前工程化版本是 `tuige_shortline_v1`，优先落地“可量化且可复测”的部分。
- 题材语义、公告语义、盘口封单博弈等仍属于下一阶段增强项。
