# a-share-paper-trading AI 使用流程

这份文档说明如何把 `a-share-paper-trading` 配到常见 AI 工具里使用，并给出安装、提问方式和典型使用案例。

适用场景：

- 想让 AI 帮你启动和管理 A 股模拟盘
- 想用 AI 下模拟单、查持仓、看成交、跑简单回测
- 想把策略信号接到模拟执行层

## 这个 skill 做什么

`a-share-paper-trading` 负责：

- 多账户模拟交易
- 限价单 / 市价单 / 撤单
- 持仓、订单、成交、账户净值
- A 股规则校验
- 简单回测

它适合：

- 演练交易流程
- 验证风控与撮合逻辑
- 将其他 skill 的信号接到模拟盘

## 运行前提

这个 skill 的交易服务、CLI 和账户逻辑都在本目录内，不依赖其他 skill 才能启动。

但如果你想让 AI 基于信号去下模拟单，建议配套安装：

- `a-share-data`
- `a-share-strategy-mainboard-multi-swing-defensive`

## 安装到 AI 工具

以下命令都在仓库根目录执行。

### Codex

```bash
mkdir -p ~/.agents/skills
cp -R a-share-paper-trading ~/.agents/skills/
```

### Cursor

```bash
mkdir -p ~/.cursor/skills
cp -R a-share-paper-trading ~/.cursor/skills/
```

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -R a-share-paper-trading ~/.claude/skills/
```

### Qoder

```bash
mkdir -p ~/.qoder/skills
cp -R a-share-paper-trading ~/.qoder/skills/
```

### OpenCode

```bash
mkdir -p ~/.opencode/skills
cp -R a-share-paper-trading ~/.opencode/skills/
```

### openclaw

```bash
mkdir -p ~/.openclaw/workspace/skills
cp -R a-share-paper-trading ~/.openclaw/workspace/skills/
```

## 让 AI 启动服务

更推荐直接让 AI 帮你启动、检查和停止服务，而不是自己手动执行命令。

可以直接这样问：

- `用 a-share-paper-trading 启动模拟盘服务`
- `用 a-share-paper-trading 检查模拟盘服务状态`
- `用 a-share-paper-trading 停止模拟盘服务`

默认监听：

- `http://127.0.0.1:18765`

默认数据库位置：

- macOS: `~/Library/Application Support/a-share-paper-trading/paper_trading.db`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/a-share-paper-trading/paper_trading.db`

## AI 工具里怎么问

建议在问题里直接点名 `a-share-paper-trading`。

### 最常用问法

- `用 a-share-paper-trading 启动模拟盘服务`
- `用 a-share-paper-trading 创建一个名为 calm1、初始资金 1000000 的模拟账户`
- `用 a-share-paper-trading 给 calm1 账户买入 600519 100 股`
- `用 a-share-paper-trading 查看 calm1 的持仓、订单和成交`
- `用 a-share-paper-trading 跑 600519 的简单回测`

### 带执行语义的问法

- `用 a-share-paper-trading 创建账户 calm1，初始资金 500000`
- `用 a-share-paper-trading 给 calm1 下 600519 的市价买单 100 股`
- `用 a-share-paper-trading 给 calm1 下 600519 的限价卖单，价格 1450，数量 100`
- `用 a-share-paper-trading 撤掉 calm1 当前未成交订单`

## AI 背后实际会跑什么

服务层：

- `scripts/paper_trading_service.py`
- `scripts/paper_trading_ctl.py`

CLI 层：

- `scripts/paper_trade_cli.py`

如果你让 AI 执行“启动 / 状态 / 停止”，它通常会跑这些命令：

```bash
SKILL_DIR="$(pwd)/a-share-paper-trading"
python3 "$SKILL_DIR/scripts/paper_trading_ctl.py" start
python3 "$SKILL_DIR/scripts/paper_trading_ctl.py" status
python3 "$SKILL_DIR/scripts/paper_trading_ctl.py" stop
```

其他常用命令：

```bash
SKILL_DIR="$(pwd)/a-share-paper-trading"

python3 "$SKILL_DIR/scripts/paper_trade_cli.py" create-account calm1 --cash 500000
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" list-accounts
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" show-account calm1
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" positions calm1
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" orders calm1
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" trades calm1
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" buy calm1 600519 100 --market
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" sell calm1 600519 100 --price 1450
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" cancel <order_id>
python3 "$SKILL_DIR/scripts/paper_trade_cli.py" backtest 600519 --strategy sma_cross --start 2025-01-01 --end 2026-03-31 --cash 200000
```

## 使用案例

### 案例 1：第一次建模拟账户

可以这样问：

- `用 a-share-paper-trading 创建一个名为 calm1 的模拟账户，初始资金 1000000`

适合场景：

- 第一次初始化模拟盘
- 想让 AI 帮你把账户和默认资金准备好

### 案例 2：执行一笔模拟交易

可以这样问：

- `用 a-share-paper-trading 给 calm1 买入 600519 100 股，市价单`

适合场景：

- 验证下单流程
- 模拟盘演练

### 案例 3：检查账户状态

可以这样问：

- `用 a-share-paper-trading 看 calm1 的账户资金、持仓、未完成订单和最近成交`

适合场景：

- 盘后复盘
- 下单前检查

### 案例 4：接策略信号执行

可以这样问：

- `先用 a-share-strategy-mainboard-multi-swing-defensive 给我今日买入参考，再用 a-share-paper-trading 把第一只候选下模拟单`

适合场景：

- 信号到执行的联动
- 模拟完整交易流程

## 注意事项

- 不要重复启动多个服务实例
- 市价单只在连续竞价时段接受
- 卖出遵守 `T+1`
- 买入数量必须是 `100` 股整数倍
- 超过涨跌停范围的价格会被拒绝

## 与其他 skill 的关系

- `a-share-data`: 数据层
- `a-share-strategy-mainboard-multi-swing-defensive`: 信号层
- `a-share-paper-trading`: 执行层

如果你想做完整闭环，推荐一起安装这三者。
