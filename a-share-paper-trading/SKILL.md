---
name: a-share-paper-trading
description: A股模拟盘交易与回测技能。Use when 用户要启动模拟仓服务、创建多账户、下限价单/市价单、撤单、查询持仓资金、验证涨跌停成交逻辑或运行A股回测。
---

# A股模拟盘

独立的模拟盘 skill。交易服务、CLI、账户、撮合与行情适配都在本目录内，不依赖其他 skill 脚本。

## 何时使用

- 启动或检查模拟盘服务
- 创建/重置账户
- 限价买卖、市价买卖、撤单
- 查询账户、持仓、订单、成交
- 验证涨跌停、T+1、收盘过期
- 跑简单回测

## 启动

```bash
SKILL_DIR="<本skill绝对路径>"
python3 "$SKILL_DIR/scripts/paper_trading_service.py" --host 127.0.0.1 --port 18765
```

默认监听 `http://127.0.0.1:18765`，默认数据库不再落在 skill 目录，而是落到用户级数据目录：

- macOS: `~/Library/Application Support/a-share-paper-trading/paper_trading.db`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/a-share-paper-trading/paper_trading.db`

若本机该端口**已有**模拟盘进程在跑，**不要**再启动第二个实例：会报 `Address already in use`，且多进程可能争用同一 SQLite 库文件。启动前可先检查端口是否在监听，例如：

```bash
lsof -iTCP:18765 -sTCP:LISTEN
```

或向 `http://127.0.0.1:18765/accounts` 发 `GET`（CLI 默认 `--base-url` 与此一致）。已有服务时直接用 `paper_trade_cli.py` 即可。

更推荐使用控制脚本常驻运行：

```bash
python3 "$SKILL_DIR/scripts/paper_trading_ctl.py" start
python3 "$SKILL_DIR/scripts/paper_trading_ctl.py" status
python3 "$SKILL_DIR/scripts/paper_trading_ctl.py" stop
```

在 macOS 上，如需持续自启动，可安装 launchd：

```bash
python3 "$SKILL_DIR/scripts/paper_trading_ctl.py" install-launchd
```

服务会：
- 交易时段定时撮合挂单
- 非交易时段停止撮合
- 收盘后让当日未成单过期
- 定时写账户净值快照

可用启动参数：

- `--host`
- `--port`
- `--db-path`
- `--match-interval`
- `--valuation-interval`
- `--idle-valuation-interval`

默认端口与 CLI 基址已改为 `18765`，避免和常见本地开发服务冲突。

## CLI

```bash
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" create-account alpha --cash 500000
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" list-accounts
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" show-default-account
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" set-default-account alpha
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" reset-account alpha --cash 300000
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" add-cash alpha 50000 --note 入金
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" deduct-cash alpha 10000 --note 出金
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" buy alpha 600519 100 --market
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" sell alpha 600519 100 --price 1450
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" orders alpha
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" positions alpha
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" show-account alpha
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" trades alpha
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" cancel <order_id>
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" process-orders
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" run-snapshots
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" backtest 600519 --strategy sma_cross --start 2025-01-01 --end 2026-03-31 --cash 200000
```

支持的 CLI 子命令：

- `create-account`
- `show-default-account`
- `set-default-account`
- `reset-account`
- `list-accounts`
- `show-account`
- `positions`
- `orders`
- `trades`
- `buy`
- `sell`
- `cancel`
- `add-cash`
- `deduct-cash`
- `process-orders`
- `run-snapshots`
- `backtest`

## Agent 执行规则（账户路由）

- 首次创建模拟账户前，必须先向用户确认初始资金金额。
- 若系统存在多个账户且用户未指明账户，先反问“本次操作哪个账户”再继续。
- 若仅有一个账户且该账户已存在，默认直接使用该账户。
- 若存在默认账户（`show-default-account` 可查），且用户未指定账户，优先使用默认账户。
- 需要切换默认账户时，使用 `set-default-account`。

### 首次初始化资金规则（默认 100w）

- 当用户首次要进行交易但尚未初始化账户资金时，先反问确认，不直接执行。
- 默认建议初始资金为 `1000000`（100w），提问模板建议为：
  - “当前未初始化模拟账户，默认按 100w 启动，是否确认？如需修改请直接给出金额。”
- 仅在用户明确确认后，才执行创建默认账户。
- 若用户给出其他金额，按用户金额创建并继续后续操作。

## CLI 参数约束（Agent 必读）

- `buy/sell`：
  - 限价单必须带 `--price`。
  - 市价单使用 `--market`，不应再传 `--price`。
- `orders --status` 可用值：`open` / `filled` / `cancelled` / `expired` / `rejected`。
- `add-cash` / `deduct-cash` 的 `amount` 必须为正数，单位为人民币元。
- 默认优先使用 `--json` 输出，便于后续结构化解析与决策。

## 执行前检查（下单前固定三步）

1. 先确认账户路由：`show-default-account` 或 `list-accounts`。
2. 再确认资金：`show-account <account_id>`。
3. 下单前确认持仓与未完成单：`positions <account_id>` 与 `orders <account_id> --status open`。

## 资金调整规则（加减可用资金）

- 入金使用 `add-cash <account_id> <amount>`，出金使用 `deduct-cash <account_id> <amount>`。
- 入金/出金金额必须为正数。
- 出金只能减少可用资金，不得穿透冻结资金；可用不足时应先告知用户再调整。

## 常见错误与处理动作

- `Address already in use`：不要重复启动服务，直接使用现有服务地址。
- `default account not set`：触发首次初始化反问流程，确认金额后创建默认账户。
- `insufficient available cash`：提示当前可用资金，建议入金或降低下单数量/价格。
- `insufficient sellable qty`：提示可卖数量，说明可能受 T+1 影响或持仓不足。
- `order is not open`：先查询订单状态（可能已成交/已撤/已过期），再决定下一步。
- `market orders are only accepted during trading hours`：改用限价单或等待交易时段。

## 规则摘要

- 只支持 A 股 long-only
- 买入数量必须是 100 股整数倍
- 卖出遵守 T+1
- 限价单价格必须符合 `0.01` 元最小报价单位
- 板块涨跌幅兜底规则：
  - 主板普通股 `10%`
  - 创业板/科创板 `20%`
  - 主板 ST `5%`
- 限价单价格不能超出当日涨跌停
- 一字涨停默认买不进
- 一字跌停默认卖不出
- 市价单仅在连续竞价时段接受
- 集合竞价与午休时段不做自动撮合
- 行情时间戳不是当日时，视为陈旧行情，不执行市价成交
- 费用模型包含最低佣金、卖出印花税、沪市过户费
- 当日单收盘后过期

## 结构

- `scripts/paper_trading_service.py`: 启动 HTTP 服务
- `scripts/paper_trade_cli.py`: CLI
- `scripts/paper_trading_ctl.py`: 启停、状态、launchd 安装
- `scripts/paper_trading_runtime.py`: 运行时默认目录、端口、路径
- `scripts/paper_trading/`: 账户、撮合、估值、数据适配

## 服务接口

默认暴露这些 HTTP 路由：

- `GET /accounts`
- `GET /accounts/default`
- `POST /accounts`
- `POST /accounts/default`
- `GET /accounts/{account_id}`
- `POST /accounts/{account_id}/reset`
- `POST /accounts/{account_id}/cash-adjust`
- `GET /accounts/{account_id}/positions`
- `GET /accounts/{account_id}/orders`
- `GET /accounts/{account_id}/trades`
- `POST /orders`
- `POST /orders/{order_id}/cancel`
- `POST /orders/process`
- `POST /snapshots/run`
- `POST /backtest`
- `GET /health`

## 参考

- GitHub 项目地址：[https://github.com/shouldnotappearcalm/a-share-skill](https://github.com/shouldnotappearcalm/a-share-skill)
