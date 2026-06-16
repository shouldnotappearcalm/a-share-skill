# DangInvest API 参考

脚本：`scripts/fetch_danginvest.py`  
数据源：[https://dang-invest.com](https://dang-invest.com)

**适用场景**（均用本脚本，由 SKILL 路由至此文档）：
- 今日/盘中**热门概念**、**热门行业**
- **概念涨跌幅**、**行业涨跌幅**（领涨、领跌、成交额、总市值排序）
- 板块热力图、某行业/概念**成分股**明细
- 7×24 **市场快讯**

## 能力概览

| 子命令 | 接口 | 说明 |
|--------|------|------|
| `--news` | `/api/market/news` | 7x24 市场快讯 |
| `--summary` | `/api/market/boards/summary` | 板块热力图列表 |
| `--detail` | `/api/market/boards/detail` | 板块成分股列表 |

所有 HTTP 请求均带重试（urllib3 Retry + 应用层重试，默认 `--retries 2`）。

---

## 板块维度 `--mode`

页面 Tab 与 API `mode` 对应关系：

| 别名 | API mode | 说明 | 板块总数（约） |
|------|----------|------|----------------|
| `sub` / `ths_industry` / `细分行业` | `ths_industry` | 细分行业（同花顺 GICS 风格） | 588 |
| `major` / `industry` / `大类行业` | `industry` | 大类行业 | 110 |
| `concept` / `ths_concept` / `概念` | `ths_concept` | 概念 | 396 |

默认 `--mode sub`（细分行业）。

---

## 排序 `--sort`

| 别名 | API sort | UI 含义 |
|------|----------|---------|
| `market_cap_desc` / `总市值` | `market_cap_desc` | 总市值 |
| `turnover_desc` / `成交额` / `总成交额` | `turnover_desc` | 总成交额 |
| `change_desc` / `涨幅` / `领涨` | `change_desc` | 涨幅 |
| `change_asc` / `跌幅` / `领跌` | `change_asc` | 跌幅 |

默认 `--sort change_desc`（涨幅/领涨）。

**注意**：`--detail` 不支持 `changePct_desc` / `changePct_asc`，会报错。涨幅/跌幅请用 `change_desc` / `change_asc`。

---

## 涨幅/跌幅查询惯例

用户问「今天热门概念/热门行业是什么」「涨/跌最多的是哪些板块」「热点是什么」「领跌行业/概念」等，但**没有明确指定**查哪类维度时：

1. **同时查三个维度**，分别拉 `--summary`：
   - **大类行业**：`--mode major`（`industry`，110 个）
   - **细分行业**：`--mode sub`（`ths_industry`，588 个）
   - **概念**：`--mode concept`（`ths_concept`，396 个）
2. **排序**：涨幅用默认 `change_desc`（或 `--sort 涨幅`）；跌幅用 `--sort change_asc`（或 `--sort 跌幅` / `领跌`）。
3. **回复时分块呈现**，标明「大类行业」「细分行业」「概念」，避免混为一谈。
4. 用户若需要成分股，再对感兴趣的板块分别 `--detail`（从 summary 的 `groupKey` 取值）。

示例（今日涨幅 Top 10，三个维度各一份）：

```bash
python3 fetch_danginvest.py --summary --mode major --limit 10 --json
python3 fetch_danginvest.py --summary --mode sub --limit 10 --json
python3 fetch_danginvest.py --summary --mode concept --limit 10 --json
```

示例（今日跌幅 Top 10）：

```bash
python3 fetch_danginvest.py --summary --mode major --sort change_asc --limit 10 --json
python3 fetch_danginvest.py --summary --mode sub --sort change_asc --limit 10 --json
python3 fetch_danginvest.py --summary --mode concept --sort change_asc --limit 10 --json
```

若用户指定了某一维度（如「概念涨幅 Top 5」「细分行业谁跌最多」「大类行业领涨」），只查对应 `--mode` 即可。

---

## groupKey 格式

从 `--summary --json` 返回的 `groupKey` 字段取值，传给 `--group-key`：

| mode | 示例 |
|------|------|
| `ths_industry` | `I:信息技术(A股)` |
| `industry` | `元器件` |
| `ths_concept` | `N:先进封装` |

---

## 命令示例

### 市场新闻

```bash
python3 fetch_danginvest.py --news --limit 50 --json
python3 fetch_danginvest.py --news --limit 120 --offset 0
```

### 板块概览（三个维度 × 四种排序）

```bash
# 细分行业 · 涨幅（默认 sort，可省略 --sort change_desc）
python3 fetch_danginvest.py --summary --mode sub --limit 300 --json

# 细分行业 · 成交额
python3 fetch_danginvest.py --summary --mode sub --sort turnover_desc --limit 300 --json

# 细分行业 · 总市值
python3 fetch_danginvest.py --summary --mode sub --sort market_cap_desc --limit 300 --json

# 细分行业 · 跌幅
python3 fetch_danginvest.py --summary --mode sub --sort change_asc --limit 300 --json

# 大类行业 · 涨幅（默认 sort）
python3 fetch_danginvest.py --summary --mode major --limit 300 --json

# 概念 · 涨幅（默认 sort）
python3 fetch_danginvest.py --summary --mode concept --limit 300 --json
```

### 板块成分明细

```bash
# 细分行业 · 印制电路板 · 总市值
python3 fetch_danginvest.py --detail --mode sub --group-key "I:印制电路板" --sort market_cap_desc --json

# 大类行业 · 元器件 · 成交额
python3 fetch_danginvest.py --detail --mode major --group-key 元器件 --sort turnover_desc --json

# 概念 · 先进封装 · 涨幅（默认 sort）
python3 fetch_danginvest.py --detail --mode concept --group-key "N:先进封装" --json

# 分页（超过 300 只时）
python3 fetch_danginvest.py --detail --mode concept --group-key "N:深股通" \
  --sort market_cap_desc --items-limit 300 --items-offset 300 --json
```

---

## 输出格式

加 `--json` 时结构：

```json
{
  "meta": {
    "url": "...",
    "tradeDate": "2026-06-16",
    "data_source": "DangInvest",
    "update_time": "..."
  },
  "data": []
}
```

- `--summary`：`data` 为板块数组
- `--detail`：`data` 含 `summary` / `items` / `itemsMeta`
- `--news`：`data` 为新闻数组

不加 `--json` 时打印可读摘要（默认最多 20 条）。

---

## 原始 API URL 对照

```text
GET /api/market/news?limit=N&offset=M

GET /api/market/boards/summary?mode={mode}&limit=N&sort={sort}

GET /api/market/boards/detail?mode={mode}&groupKey={key}&sort={sort}&items_limit=N&items_offset=M
```

---

## 与 fetch_realtime.py 的关系

`fetch_realtime.py` 仍保留 `--market-news` / `--boards-summary` / `--boards-detail` 作为兼容入口。  
新能力请优先使用 `fetch_danginvest.py`（mode/sort 别名更完整，detail 参数校验更严格）。
