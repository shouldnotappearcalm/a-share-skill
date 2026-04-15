# a-share-data

基于 A 股市场的数据分析 Skill 集合，提供实时行情、历史与财务、技术指标等多种能力，面向 Agent 使用。

## 目录结构与 Skill 列表

```bash
a-share-skill/
  a-share-data/                                   # A股综合数据分析
  a-share-paper-trading/                          # 模拟盘交易与回测
  a-share-strategy-mainboard-multi-swing-defensive/  # 主板动态池趋势回踩：买卖决策信号
  macd-trend-resonance-stock-picker/              # 均线 + MACD 趋势共振选股
  README.md
```

说明：当前仓库已采用扁平结构，每个 skill 目录直接位于仓库根目录下；每个 skill 内部保持 `SKILL.md + scripts/ + references/` 的标准结构。

当前包含的 Skill：

- `a-share-data`：A 股综合数据分析 Skill  
  - **主要能力**（摘自 `SKILL.md`）：  
    - 实时行情快照（分钟K线聚合 + 市场状态）、今日分钟K线、批量实时行情  
    - 分钟 / 日 / 周 K 线（腾讯/新浪 API + 东方财富 akshare）  
    - 12 类技术指标（MA / EMA / MACD / KDJ / RSI / WR / BOLL / BIAS / CCI / ATR / DMI / TAQ）  
    - 盈利 / 成长 / 偿债 / 现金流 / 杜邦等六维财务报表  
    - 热点概念板块、北向资金、龙虎榜、涨停板 / 连板股、个股资金流向  
    - 沪深300 / 上证50 / 中证500 指数成分股、存款利率 / 货币供应量等宏观数据  
  - **典型使用场景**：  
    - 帮用户做单只股票的综合分析（行情 + 技术面 + 基本面）  
    - 盘中情绪与热点跟踪（指数、涨跌停统计、热点板块、北向资金、龙虎榜）  
    - 为量化 / 回测准备历史行情与财务因子数据

- `a-share-paper-trading`：A 股模拟交易与回测 Skill  
  - **主要能力**：  
    - 创建/重置模拟账户，管理资金与持仓  
    - 限价单/市价单下单、撤单、订单与成交查询  
    - 交易规则约束（100股整数倍、T+1、涨跌停校验、收盘过期）  
    - 账户估值与净值快照、简单策略回测  
  - **典型使用场景**：  
    - 在不动真资金的情况下做交易流程演练  
    - 验证撮合、冻结资金、可卖数量等账户逻辑  
    - 快速回测单票策略并观察收益曲线

- `a-share-strategy-mainboard-multi-swing-defensive`：主板流动性池 + 日线 `trend_pullback` 的**选股与买卖信号** Skill  
  - **主要能力**（见该目录 `SKILL.md`）：  
    - 从主板高成交额股票中取前 N 只构成股票池（`MarketDataProvider.get_mainboard_universe`）  
    - 输出「上一交易日收盘 entry」与「最新收盘 entry」两类买入参考，默认按 `score` 各取前 5 只（可调 `--max-buys`）  
    - 可选读取持仓文件，标注最新日线是否满足策略 `exit`（卖出参考）  
  - **典型使用场景**：  
    - 盘前或盘后生成当日可关注标的与减仓参考  
    - 与 `a-share-paper-trading` 配合时：先跑信号脚本，再按需向模拟盘下单（本 skill 不自动下单）  
  - **说明**：不包含混合回测；策略参数在 `scripts/strategy_lab/strategy_params.py`

- `macd-trend-resonance-stock-picker`：基于“均线定方向，MACD 定节奏”的趋势共振选股 Skill  
  - **主要能力**：  
    - 先按 60 日线方向与股价相对位置做趋势硬过滤  
    - 再按 MACD（0 轴位置、金叉/红柱、日线与 60 分钟共振）做节奏确认  
    - 输出 A/B/C/D 四档候选分级、触发条件、失效条件与风控提示  
    - 提供 100 分评分框架与 `EXECUTE/LIGHT/OBSERVE/AVOID` 动作映射  
  - **典型使用场景**：  
    - 盘前生成候选池并区分强弱优先级  
    - 盘中结合触发条件识别回踩再上或突破买点  
    - 盘后复盘顶背离减仓与趋势失效信号

## 全局安装（openclaw / cursor / claude code / opencode / codex）

以下写法以“安装到用户级全局目录”为主，适合你这种一套技能多项目复用的场景。命令在本仓库根目录执行。

### openclaw

方式一：通过 ClawHub 安装（推荐，便于版本管理）

```bash
clawhub install a-share-trading
clawhub install a-share-paper-trading
```

发布页：
- `https://clawhub.ai/shouldnotappearcalm/a-share-trading`
- `https://clawhub.ai/shouldnotappearcalm/a-share-paper-trading`

方式二：从本仓库复制到全局目录

```bash
mkdir -p ~/.openclaw/workspace/skills
cp -R a-share-data ~/.openclaw/workspace/skills/
cp -R a-share-paper-trading ~/.openclaw/workspace/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.openclaw/workspace/skills/
cp -R macd-trend-resonance-stock-picker ~/.openclaw/workspace/skills/
```

### Cursor

```bash
mkdir -p ~/.cursor/skills
cp -R a-share-data ~/.cursor/skills/
cp -R a-share-paper-trading ~/.cursor/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.cursor/skills/
cp -R macd-trend-resonance-stock-picker ~/.cursor/skills/
```

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -R a-share-data ~/.claude/skills/
cp -R a-share-paper-trading ~/.claude/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.claude/skills/
cp -R macd-trend-resonance-stock-picker ~/.claude/skills/
```

### OpenCode

```bash
mkdir -p ~/.opencode/skills
cp -R a-share-data ~/.opencode/skills/
cp -R a-share-paper-trading ~/.opencode/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.opencode/skills/
cp -R macd-trend-resonance-stock-picker ~/.opencode/skills/
```

如果你的 OpenCode 使用的是自定义 skills 路径，请把上面的目录替换成你本机配置路径。

### Codex

```bash
mkdir -p ~/.agents/skills
cp -R a-share-data ~/.agents/skills/
cp -R a-share-paper-trading ~/.agents/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.agents/skills/
cp -R macd-trend-resonance-stock-picker ~/.agents/skills/
```

### 安装后快速自检

1. 确认目标目录下存在 `a-share-data/SKILL.md`、`a-share-paper-trading/SKILL.md`、`a-share-strategy-mainboard-multi-swing-defensive/SKILL.md` 与 `macd-trend-resonance-stock-picker/SKILL.md`
2. 新开会话后发一个明确请求，例如：
   - “用 a-share-data 拉取 600519 最近 20 个交易日的日线”
   - “用 a-share-paper-trading 创建模拟账户并下一个限价单”
   - “用 a-share-strategy-mainboard-multi-swing-defensive 跑 `daily_decisions.py` 看今日买入参考”
  - “用 macd-trend-resonance-stock-picker 生成今日 A/B/C/D 候选并给出触发与失效条件”

### 参考文档

- Cursor: [Agent Skills](https://www.trycursor.com/docs/context/skills)
- Claude Code: [Extend Claude with skills](https://code.claude.com/docs/en/skills.md)
- Codex: [Agent Skills](https://developers.openai.com/codex/skills)
