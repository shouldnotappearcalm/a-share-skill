---
name: ai-stock-pick-skill
description: AI 辅助 A 股选股与策略执行框架。先从外部信息源（例如 Telegram 公开频道、后续更多数据源/策略脚本）抓取或生成结构化信号，再结合 A 股市场数据进行标的映射、评分与结论输出。Use when: 用户希望基于“AI 相关外部信息”自动生成 A 股选股/观察列表，并需要按时间窗口拉取输入信号以及输出结构化可分析结果。
---

# AI 新闻选股输入（Telegram 抓取）

本 skill 的目标是把 Telegram 公开频道的“海外 AI 大厂消息”转成可结构化处理的数据。

## 第一个脚本：抓取频道消息

脚本：`scripts/fetch_tg_messages.py`

### 用法示例

```bash
python3 scripts/fetch_tg_messages.py \
  --channel AI_News_CN \
  --start 2026-03-18 \
  --end 2026-03-19 \
  --limit 200 \
  --json
```

当 `--start/--end` 只提供日期（`YYYY-MM-DD`）时：
- `--start` 默认从当天 `00:00:00` 开始
- `--end` 默认到当天 `23:59:59.999999` 为止

### 运行参数

- `--channel`：Telegram 频道名（不带 `@`），例如 `AI_News_CN`
- `--start`：开始时间（`YYYY-MM-DD` 或 ISO 8601）
- `--end`：结束时间（`YYYY-MM-DD` 或 ISO 8601）
- `--tz`：当时间字符串不带时区时采用的时区，默认 `Asia/Shanghai`
- `--limit`：最多返回多少条消息（默认 200）
- `--max-pages`：最多翻页多少次（默认 20）
- `--json`：输出 JSON（不加则输出纯文本摘要）

### 依赖

脚本会从公开页面 `https://t.me/s/<channel>` 抓取消息（无需 Telegram API Key）。
需要安装：

```bash
pip install requests beautifulsoup4
```

