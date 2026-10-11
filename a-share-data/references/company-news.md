# 公司近期新闻与公告

入口：`scripts/fetch_company_news.py`，Python 3.9+，只依赖 `requests`。

用户问「某公司最近有什么资讯」「这周公告」「最新消息」时优先此入口。
先确定股票代码；已知证券简称时提供 `--name`，否则通过腾讯行情自动解析简称。
不要将公司名随意截短，否则可能混入其他公司。

```bash
python3 "$SKILL_DIR/scripts/fetch_company_news.py" --code 300476 --name 胜宏科技 --days 7 --json
python3 "$SKILL_DIR/scripts/fetch_company_news.py" --code 000001 --days 30 --scope news --json
python3 "$SKILL_DIR/scripts/fetch_company_news.py" --code 600519 --days 30 --scope announcements --json
```

| 参数 | 默认 | 含义 |
|---|---|---|
| `--code` | 必填 | 六位代码，支持 sh/sz/bj 前缀及 .SH/.SZ/.BJ/.XSHG/.XSHE 后缀 |
| `--name` | 自动解析 | 精确证券简称 |
| `--days` | 7 | 自然日，含今天，Asia/Shanghai，范围1–366 |
| `--scope` | all | all / news / announcements |
| `--limit` | 20 | 合并去重后最多条数，1–200 |
| `--pages` | 2 | 每个来源最多页数，1–5；不是保证完整覆盖 |
| `--max-seconds` | 20 | 整体等待上限，1–60秒；保留已完成源的结果 |
| `--title-only` | 关闭 | 可选精确标题过滤；默认保留上游候选，由调用方判断语义 |
| `--no-cache` | 关闭 | 跳过结果缓存，重新查询；代码映射仍可用缓存 |
| `--json` | 关闭 | 结构化输出 |

数据路线：

- 新闻：东方财富检索 API，代码+精确简称并发，`sort=time`，过滤查询窗口。默认保留上游候选，不按标题/摘要规则丢弃新闻；`matched_in` 只记录精确文本出现位置。`000001` 的候选可能涉及上证指数，调用方需判断；可显式加 `--title-only` 收紧。
- 公告：巨潮代码→orgId映射与公告查询，同时查东方财富公告。相同标题+日期优先保留巨潮原文链接。
- 各源独立失败诊断；每线程复用HTTP连接，连接/TLS异常在总预算内最多重试一次。整体超时停止等待，返回已完成结果；分页翻到窗口之外即停止。
- 成功结果和原始HTTP响应分别缓存5分钟，跨days/limit复用；巨潮代码映射缓存7天。`--no-cache` 绕过两层资讯缓存。各源记录 `cache_hits/network_requests/fetched_at`，保留实际获取时间，不以缓存查询时间冒充数据更新时间。

返回顶层 `status/code/name/meta/data`。

| status | 含义 |
|---|---|
| ok | 所有请求源响应成功，窗口内有匹配 |
| empty | 所有请求源响应成功，在已查询页中没有匹配；仍需看 coverage_limited |
| partial | 部分源失败/超时，其他源已响应；可能有数据，也可能没有 |
| unavailable | 所有请求源失败/超时，CLI非零退出 |

`data[]` 包含 `kind`（news/announcement）、`title`、`summary`、`published_at`（带时区）、`publisher`、`provider`、`url`、`matched_in`、`source_categories`。
`meta.sources[]` 记录每源状态、耗时、抓取条数、分页截断及异常。
`meta.latest_news_at/latest_announcement_at` 是窗口内匹配结果的最新时间，`meta.coverage_limited` 表示输出或分页被截断。

解读约束：

- summary 是检索摘要，公告只有标题和链接；原文结论需要继续阅读链接。
- 不推断事件类别、情绪或相关性评分。`source_categories` 仅保留上游原始分类，有些源没有分类；空数组不能解释为没有某类事件。
- 候选可能含行业综述/ETF推广，由调用方判断关联程度；`--title-only` 可选过滤，但可能降低召回。
- 新闻和公告并非同类证据；一篇新闻转述了公告，不等于独立验证了两次。
- 空结果可扩大到30天或增加分页重查，但不得说“公司没有发生任何事件”。失败不能解释为无事件。
- `fetch_stock_events.py` 已复用此路径，返回 `recent_information`，通过 `--news-days` 控制窗口（默认30天）。旧分类字段状态为 `unclassified`，空列表不能解释为没有监管/合同事件。业绩历史与热榜是其他独立接口。

复查全部数据入口：

```bash
python3 "$SKILL_DIR/scripts/check_data_health.py" --output /tmp/a-share-health --workers 4 --timeout 35
python3 "$SKILL_DIR/scripts/check_data_health.py" --only company_news,events --output /tmp/a-share-news-health
```

体检不执行任何选股、回测或交易脚本。它同时检查 JSON/空数据/来源异常/部分语义问题，不保证所有字段正确。
