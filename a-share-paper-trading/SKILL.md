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
python3 "$SKILL_DIR/scripts/paper_trading_service.py" --host 127.0.0.1 --port 8765
```

默认监听 `http://127.0.0.1:8765`。若本机该端口**已有**模拟盘进程在跑，**不要**再启动第二个实例：会报 `Address already in use`，且多进程可能争用同一 SQLite 库文件。启动前可先检查端口是否在监听，例如：

```bash
lsof -iTCP:8765 -sTCP:LISTEN
```

或向 `http://127.0.0.1:8765/accounts` 发 `GET`（CLI 默认 `--base-url` 与此一致）。已有服务时直接用 `paper_trade_cli.py` 即可。

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

## CLI

```bash
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" create-account alpha --cash 500000
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" list-accounts
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" reset-account alpha --cash 300000
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
- `reset-account`
- `list-accounts`
- `show-account`
- `positions`
- `orders`
- `trades`
- `buy`
- `sell`
- `cancel`
- `process-orders`
- `run-snapshots`
- `backtest`

## 规则摘要

- 只支持 A 股 long-only
- 买入数量必须是 100 股整数倍
- 卖出遵守 T+1
- 限价单价格不能超出当日涨跌停
- 一字涨停默认买不进
- 一字跌停默认卖不出
- 当日单收盘后过期

## 结构

- `scripts/paper_trading_service.py`: 启动 HTTP 服务
- `scripts/paper_trade_cli.py`: CLI
- `scripts/paper_trading/`: 账户、撮合、估值、数据适配

## 服务接口

默认暴露这些 HTTP 路由：

- `GET /accounts`
- `POST /accounts`
- `GET /accounts/{account_id}`
- `POST /accounts/{account_id}/reset`
- `GET /accounts/{account_id}/positions`
- `GET /accounts/{account_id}/orders`
- `GET /accounts/{account_id}/trades`
- `POST /orders`
- `POST /orders/{order_id}/cancel`
- `POST /orders/process`
- `POST /snapshots/run`
- `POST /backtest`
- `GET /health`

## 数据层说明

本 skill 的行情/历史数据适配逻辑已内置在 `scripts/paper_trading/market_data.py`，可单独复制与运行，不需要依赖外部 skill 目录。
