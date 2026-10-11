# 历史、行业、日期与缓存

从技能根目录运行以下命令；具体参数以各脚本`--help`为准。

## 历史K线与复权

```bash
python3 scripts/fetch_history.py --kline 600519 --adjust raw --count 10 --with-meta --json
python3 scripts/fetch_history.py --kline 600519 --adjust qfq --start 2026-01-01 --end 2026-09-30 --count 120 --no-cache --with-meta --json
python3 scripts/fetch_history.py --kline-batch 600519,000001 --adjust hfq --count 10 --workers 4 --json
```

| 参数 | 含义 |
|---|---|
| `--adjust raw/qfq/hfq` | 默认raw；腾讯、东财按同一请求口径读取，新浪仅用于raw |
| `--freq d/w/m`或`1d/1w/1M` | 日/周/月；默认1d |
| `--start/--end` | 日期范围YYYY-MM-DD |
| `--count` | 返回条数，默认120；旧`--limit`会映射为count |
| `--with-meta` | 单票K线JSON包装为data/meta，附来源、口径、时区、源错误和缓存信息 |
| `--no-cache` | 绕过历史结果缓存并完整拉取 |

默认JSON仍为裸数组，字段含time/code/open/high/low/close/preclose/volume/pctChg。批量返回逐票结果，检查ok和error。原始成交量保持供应商定义，不能假定不同源单位已统一。旧数字复权1/2/3分别映射为hfq/qfq/raw。未证明复权口径的源不会用于严格降级。

## 行业目录、成分和指数历史

```bash
python3 scripts/fetch_industry.py --action directory --taxonomy sw --level 1 --json
python3 scripts/fetch_industry.py --action directory --taxonomy sw --level 2 --json
python3 scripts/fetch_industry.py --action directory --taxonomy sw --level 3 --json
python3 scripts/fetch_industry.py --action members --taxonomy sw --symbol 801080 --json
python3 scripts/fetch_industry.py --action history --taxonomy sw --symbol 801080 --start 2026-10-01 --end 2026-10-09 --json
python3 scripts/fetch_industry.py --action directory --taxonomy eastmoney_industry --json
python3 scripts/fetch_industry.py --action directory --taxonomy eastmoney_concept --json
```

| 参数 | 含义 |
|---|---|
| `--action directory/members/history` | 目录/当前成分/行业指数历史，默认directory |
| `--taxonomy sw/eastmoney_industry/eastmoney_concept` | 明确分类，默认sw；不同标准不能混用 |
| `--level 1/2/3` | SW目录层级；供应商有父级字段时原样保留 |
| `--symbol` | members/history必填；使用该目录返回的行业代码或供应商名称 |
| `--start/--end` | 行业指数历史日期范围 |
| `--no-cache` | 绕过该次行业查询缓存 |

返回status/data/meta，data保留供应商原始列；meta含source/taxonomy/level/action/count/effective_at/cache_hit/fetched_at。SW目录与成分来源为乐咕的SW分类数据，SW指数历史来源为申万研究；东财分类明确标Eastmoney。版本、生效时间无法核实时保留null。当前成分不表示历史成分，指数历史不等于可恢复历史成分；接口失败与合法空区间分开。

## 财务指标与公告日期

```bash
python3 scripts/fetch_history.py --financials 600519 --count 4 --json
python3 scripts/fetch_history.py --financials 600519 --as-of 2026-07-01 --count 4 --json
python3 scripts/fetch_history.py --cashflow 600519 --year 2025 --json
```

start/end/year/quarter筛选报告期；as-of筛选真实公告日期，二者不同。无公告日期的源会拒绝as-of，而不是根据报告期推断。当前供应商快照未必保留历史修订，不能把日期过滤宣称为完整PIT。cashflow和dupont是相关指标，完整报表需其他有明确口径的入口。

## 板块时效

热门榜和groupKey成员走fetch_danginvest.py，详见 [板块参考](danginvest-api-reference.md)。默认保留旧快照，并返回stale/data_quality；require-fresh在陈旧或未知时效时失败，不自动替换分类体系。

## 缓存与绕过缓存

| 数据 | 缓存时间 | 绕过方式 |
|---|---:|---|
| 历史K线 | 300秒 | fetch_history的--no-cache |
| 行业目录 | 1天 | fetch_industry的--no-cache |
| 行业成分/行业指数历史 | 300秒 | fetch_industry的--no-cache |
| 全市场证券清单 | 12小时 | fetch_history --all-stocks --no-cache |
| 公司新闻结果与HTTP响应 | 各300秒 | fetch_company_news的--no-cache；巨潮身份映射仍可使用7天缓存 |

新增历史/行业缓存默认在技能cache/，可用ASHARE_DATA_CACHE_DIR设置目录，ASHARE_NO_CACHE=1绕过该通用缓存。旧新闻与证券清单有各自缓存实现，不受这个通用环境变量全面控制；分别使用其CLI参数。新闻缓存细节见 [公司资讯](company-news.md)。实时行情没有本轮新增的结果缓存，技术入口按其实现取数，不能笼统宣称所有数据都缓存。

cache_hit表示本次是否命中，fetched_at是原始获取时间，不能用查询时间替代。新增通用缓存通过临时文件原子替换；过期数据不会在源失败时冒充新数据。相同请求只在同一进程内合并；多个CLI进程仍可能重复请求。当前没有容量上限、自动清理或跨进程协调，安装到只读目录时仍可取数，但可能无法保存缓存。跨进程共享、SQLite和自动清理尚未实现。

缓存、请求合并、线程和API适配在scripts中实现。SKILL.md负责选择入口和解释结果，不要求查询任务部署缓存服务。
