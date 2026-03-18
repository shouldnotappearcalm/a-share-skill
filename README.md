# a-share-skill

基于 A 股市场的数据分析 Skill 集合，提供实时行情、历史与财务、技术指标等多种能力，面向 Agent 使用。

## 目录结构与 Skill 列表

```bash
a-share-skill/
  README.md                     # 当前总说明
  skills/
    a-share-skill/              # 单个 Skill：A 股综合数据分析
      SKILL.md                  # Skill 元信息与详细能力说明（给 Agent 看）
      scripts/                  # 可执行脚本（实时、历史/财务、技术指标）
      references/               # 文档与参数说明，例如 api-reference.md
```

当前包含的 Skill：

- `a-share-skill`：A 股综合数据分析 Skill  
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

## scripts 与 references 说明

- `scripts/`：可执行脚本，供 Agent 通过 Skill 工具调用  
  - `fetch_realtime.py`：实时行情 / 指数 / 热点板块 / 涨停连板 / 资金流向等  
  - `fetch_history.py`：历史 K 线、财务报表、指数成分、宏观经济、交易日历等  
  - `fetch_technical.py`：基于实时 K 线计算多种技术指标（依赖 MyTT）
- `references/`：补充说明文档，例如 `api-reference.md`，对各脚本参数和字段做更详细说明

## 如何在 Cursor / 项目中使用

- 将整个 `skills/a-share-skill` 目录打包，放入 `~/.cursor/skills/` 或项目 `.cursor/skills/` 中使用  
- 在此仓库下继续追加更多 Skills（例如 `skills/xxx-skill/`），保持同样结构：`SKILL.md` + `scripts/` + `references/`
