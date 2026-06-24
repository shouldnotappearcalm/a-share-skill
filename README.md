# a-share-skill

> 中文文档 / Chinese README: [README.zh.md](README.zh.md)

A collection of A-share (China Shanghai/Shenzhen) data-analysis and paper-trading skills for AI tools — built for stock analysis, quant trading, paper trading, and A-share workflows:

- `a-share-data`: market data query and analysis
- `a-share-paper-trading`: paper-trading execution and backtesting

You can simply ask your AI to:

- Look up a stock's real-time quote, historical trend, technical indicators, events, and industry info
- Create a `calm1` paper-trading account, view account details and full trade history, and place simulated orders
- Combine the broad market, your holdings, and account status to decide whether to buy, sell, hold, or do nothing today

## Trend-Pullback Strategies

`a-share-strategy-mainboard-multi-swing-defensive` (main-board trend pullback) and `a-share-strategy-allmarket-multi-swing-defensive` (all-market trend pullback) are **not open-sourced for now**.

For daily trading ideas, candidate scans, and position management, follow my Xiaohongshu (RED) account below — I keep posting updates there.

<table>
  <tr>
    <td align="center" valign="top">
      <strong>Xiaohongshu (RED)</strong><br/><br/>
      <img width="280" alt="Xiaohongshu" src="https://github.com/user-attachments/assets/7c63fe7f-14f1-487e-96db-755c75b144f4" />
    </td>
    <td align="center" valign="top">
      <strong>Xiaohongshu Group</strong><br/><br/>
      <img width="280" alt="Xiaohongshu Group" src="https://github.com/user-attachments/assets/d37b2861-24a0-4fba-a52f-18cb27fe8cb7" />
    </td>
  </tr>
</table>

## Paper Account: +40% in 2 Months

<table>
  <tr>
    <td align="center" valign="top">
      <strong>Apr 16 — account initialized with 1,000,000</strong><br/><br/>
      <img width="240" alt="account init" src="https://github.com/user-attachments/assets/ef7d9b23-b9a3-4c49-afc2-3f81fd489058" />
    </td>
    <td align="center" valign="top">
      <strong>Jun 17 — intraday +39.9% (still updating)</strong><br/>
      Current holdings: ZTE, BOE A, WUS Printed Circuit, Jiemei Technology, Yongding, Voage Optoelectronics, LION Microelectronics, Boqian New Materials<br/><br/>
      <img width="731" height="859" alt="image" src="https://github.com/user-attachments/assets/3ed0eb21-34fe-4442-b49c-9adbdca31858" />
  </tr>
</table>

## Two Core Skills

### `a-share-data`

Good for questions like:

- How is this stock doing right now?
- What's the trend over the last 60 days?
- Are there any event-driven catalysts?
- How are the CSI 300, hot sectors, and northbound capital doing right now?

Capabilities:

- Real-time quotes, historical K-line, technical indicators, events, industry, index, and macro data

Docs:

- [docs/A股数据安装使用文档.md](docs/A股数据安装使用文档.md) (Chinese)

### `a-share-paper-trading`

Good for tasks like:

- Create a `calm1` paper-trading account
- View `calm1` account details, positions, orders, and full trade history
- Place a simulated buy or sell order for `calm1`
- Run a simple backtest

Capabilities:

- Account management, order placement, cancellation, positions, orders, fills, account valuation, and backtesting

Docs:

- [docs/模拟仓安装使用文档.md](docs/模拟仓安装使用文档.md) (Chinese)

## Quickest Examples

- `Query data`: use `a-share-data` to check 600519's latest quote, the last 60 daily candles, and MACD.
- `Manage paper trading`: use `a-share-paper-trading` to create `calm1` with an initial balance of `1000000`, then view `calm1`'s account details and full trade history.

## Combined Usage

- `Data analysis`
  - `a-share-data`
  - Good for single-stock analysis, market-state monitoring, and batch data pulls

- `Paper execution`
  - `a-share-data + a-share-paper-trading`
  - Good for pulling data to form a view first, then executing simulated trades on `calm1`

## Installation

The examples below include the two core skills: `a-share-data` and `a-share-paper-trading`.

### Codex

```bash
mkdir -p ~/.agents/skills
cp -R a-share-data ~/.agents/skills/
cp -R a-share-paper-trading ~/.agents/skills/
```

### Cursor

```bash
mkdir -p ~/.cursor/skills
cp -R a-share-data ~/.cursor/skills/
cp -R a-share-paper-trading ~/.cursor/skills/
```

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -R a-share-data ~/.claude/skills/
cp -R a-share-paper-trading ~/.claude/skills/
```

### Qoder

```bash
mkdir -p ~/.qoder/skills
cp -R a-share-data ~/.qoder/skills/
cp -R a-share-paper-trading ~/.qoder/skills/
```

If you use OpenCode, openclaw, or another AI tool that supports skills, just replace the path with that tool's skills directory.

## Documentation

- [A-share Data — install & usage (Chinese)](docs/A股数据安装使用文档.md)
- [Paper Trading — install & usage (Chinese)](docs/模拟仓安装使用文档.md)

## Other Skills

- `macd-second-golden-cross`
  - Good for spotting repair-type setups like "MACD bullish divergence + a second golden cross below the zero axis"

- `macd-trend-resonance-stock-picker`
  - Good for "moving averages set the direction, MACD sets the rhythm" trend-resonance stock picking

- `tuige-shortline-trading`
  - Good for short-line trigger / invalidation / risk / position_grade decisions

## References

- Cursor: [Agent Skills](https://www.trycursor.com/docs/context/skills)
- Claude Code: [Extend Claude with skills](https://code.claude.com/docs/en/skills.md)
- Codex: [Agent Skills](https://developers.openai.com/codex/skills)
- Qoder: [Skills](https://docs.qoder.com/extensions/skills)
