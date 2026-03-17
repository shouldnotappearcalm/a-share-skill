# Changelog

## 0.1.0 - 2026-03-18

- 新增 `skills/a-share-skill` Skill：
  - 能力覆盖：实时行情、分钟/日/周K线、技术指标（MACD/KDJ/RSI/BOLL 等）、财务报表（盈利/成长/偿债/现金流/杜邦）、宏观利率与货币供应量、指数成分股、涨停/连板、龙虎榜、北向资金、资金流向等。
  - 数据源：东方财富 / 新浪财经（通过 akshare）、Baostock、本地 Ashare + MyTT 库。
- 添加脚本：
  - `scripts/fetch_realtime.py`：实时行情 + 指数 + 热点板块 + 涨停/连板 + 资金流向。
  - `scripts/fetch_history.py`：历史K线、财务报表、指数成分、宏观经济、交易日历。
  - `scripts/fetch_technical.py`：依托 Ashare 实时K线和 MyTT 计算多种技术指标并给出信号解读。
  - `scripts/Ashare.py`：内置稳定版 Ashare，实现 A 股双核心实时 K 线接口。
- 目录调整：
  - 使用 `skills/` 目录统一承载 Skill：`skills/a-share-skill/`。
  - 在仓库根目录新增 `README.md`，说明 Skill 包结构与用法。
