# a-share-skill

面向 AI 工具的 A 股数据分析、量化选股与模拟交易 skill 集合，适合 stock analysis、quant trading、paper trading、A-share strategy workflow：

- `a-share-data`：数据查询与分析
- `a-share-strategy-mainboard-multi-swing-defensive`：主板趋势回踩信号
- `a-share-strategy-allmarket-multi-swing-defensive`：全市场趋势回踩信号
- `a-share-paper-trading`：模拟盘执行与回测

你可以直接让 AI：

- 查个股实时行情、历史走势、技术指标、事件和行业信息
- 扫描主板或全市场候选，输出买入参考和持仓卖出参考
- 创建 `calm1` 模拟账户，查看账户详情、全部交易记录并下模拟单
- 结合大盘、候选、持仓和账户状态，判断今天该买、卖、持有还是不动

## AI操作分享

我会在小红书持续更新每天的操作。

<table>
  <tr>
    <td align="center" valign="top">
      <strong>小红书</strong><br/><br/>
      <img width="280" alt="小红书" src="https://github.com/user-attachments/assets/7c63fe7f-14f1-487e-96db-755c75b144f4" />
    </td>
    <td align="center" valign="top">
      <strong>小红书群</strong><br/><br/>
      <img width="280" alt="小红书群" src="https://github.com/user-attachments/assets/d37b2861-24a0-4fba-a52f-18cb27fe8cb7" />
    </td>
  </tr>
</table>

## 交流群

<img width="280" alt="交流群" src="https://github.com/user-attachments/assets/ea8b8f99-9dd2-4f4b-9010-8e2e4b79207f" />

## 模拟仓2个月 40 个点收益

<table>
  <tr>
    <td align="center" valign="top">
      <strong>4.16 初始化账户100w</strong><br/><br/>
      <img width="240" alt="7259c3d33aca6e81f948d90f89be5d15" src="https://github.com/user-attachments/assets/ef7d9b23-b9a3-4c49-afc2-3f81fd489058" />
    </td>
    <td align="center" valign="top">
      <strong>6.17 盘中 +39.9%（持续更新中）</strong><br/>
      当前持仓：中兴通讯、京东方 A、沪电股份、洁美科技、永鼎股份、沃格光电、立昂微、博迁新材<br/><br/>
      <img width="731" height="859" alt="image" src="https://github.com/user-attachments/assets/3ed0eb21-34fe-4442-b49c-9adbdca31858" />
  </tr>
</table>

## 四个核心 Skill

### `a-share-data`

适合问：

- 这只票现在怎么样
- 最近 60 天走势怎样
- 有没有事件驱动
- 沪深300、热点板块、北向资金现在怎么样

能做：

- 实时行情、历史 K 线、技术指标、事件、行业、指数与宏观数据

文档：

- [docs/A股数据安装使用文档.md](docs/A股数据安装使用文档.md)

### `a-share-strategy-mainboard-multi-swing-defensive`

适合问：

- 今天有哪些主板候选
- 我的持仓要不要卖
- 今天更适合买新票还是偏防守

能做：

- 主板池扫描、买入参考、卖出参考、批量现价快照

文档：

- [docs/主板趋势回踩策略安装使用文档.md](docs/主板趋势回踩策略安装使用文档.md)

### `a-share-strategy-allmarket-multi-swing-defensive`

适合问：

- 今天全市场有哪些趋势回踩候选
- 创业板和科创板要不要一起纳入扫描
- 同一套趋势回踩逻辑下，全市场和主板版差异是什么

能做：

- 全市场高流动性池扫描、买入参考、卖出参考、批量现价快照

文档：

- [docs/a-share-strategy-allmarket-multi-swing-defensive.md](docs/a-share-strategy-allmarket-multi-swing-defensive.md)

### `a-share-paper-trading`

适合问：

- 给 `calm1` 创建模拟账户
- 看 `calm1` 账户详情、持仓、订单、全部交易记录
- 给 `calm1` 下模拟买单或卖单
- 跑简单回测

能做：

- 账户管理、下单、撤单、持仓、订单、成交、账户估值、回测

文档：

- [docs/模拟仓安装使用文档.md](docs/模拟仓安装使用文档.md)

## 最短案例

- `查数据`：用 `a-share-data` 看 600519 最新行情、最近 60 日日线和 MACD。
- `跑主板策略`：用 `a-share-strategy-mainboard-multi-swing-defensive` 扫今天主板候选，只看最终过滤结果。
- `跑全市场策略`：用 `a-share-strategy-allmarket-multi-swing-defensive` 扫今天全市场候选，只看最终过滤结果。
- `管模拟盘`：用 `a-share-paper-trading` 创建 `calm1`，初始资金 `1000000`，再查看 `calm1` 账户详情和全部交易记录。

## 组合使用

- `数据分析`
  - `a-share-data`
  - 适合做单票分析、市场状态观察和批量拉数

- `策略判断`
  - `a-share-data + a-share-strategy-mainboard-multi-swing-defensive`
  - 适合做主板候选扫描、持仓卖出参考和环境判断

- `更宽股票池判断`
  - `a-share-data + a-share-strategy-allmarket-multi-swing-defensive`
  - 适合把创业板和科创板一起纳入趋势回踩扫描

- `模拟执行闭环`
  - `a-share-strategy-mainboard-multi-swing-defensive + a-share-paper-trading`
  - 适合让 AI 先分析，再决定是否给 `calm1` 买入、卖出、减仓或不交易

详细案例：

- [主板趋势回踩策略与模拟仓联动案例](docs/主板趋势回踩策略与模拟仓联动案例.md)

## 安装

以下示例包含四个核心 skill：`a-share-data`、`a-share-strategy-mainboard-multi-swing-defensive`、`a-share-strategy-allmarket-multi-swing-defensive`、`a-share-paper-trading`。

### Codex

```bash
mkdir -p ~/.agents/skills
cp -R a-share-data ~/.agents/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.agents/skills/
cp -R a-share-strategy-allmarket-multi-swing-defensive ~/.agents/skills/
cp -R a-share-paper-trading ~/.agents/skills/
```

### Cursor

```bash
mkdir -p ~/.cursor/skills
cp -R a-share-data ~/.cursor/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.cursor/skills/
cp -R a-share-strategy-allmarket-multi-swing-defensive ~/.cursor/skills/
cp -R a-share-paper-trading ~/.cursor/skills/
```

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -R a-share-data ~/.claude/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.claude/skills/
cp -R a-share-strategy-allmarket-multi-swing-defensive ~/.claude/skills/
cp -R a-share-paper-trading ~/.claude/skills/
```

### Qoder

```bash
mkdir -p ~/.qoder/skills
cp -R a-share-data ~/.qoder/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.qoder/skills/
cp -R a-share-strategy-allmarket-multi-swing-defensive ~/.qoder/skills/
cp -R a-share-paper-trading ~/.qoder/skills/
```

如果你用的是 OpenCode、openclaw 或其他支持 skills 的 AI 工具，只需要把路径替换成对应工具的 skills 目录。

## 文档导航

- [A股数据安装使用文档](docs/A股数据安装使用文档.md)
- [主板趋势回踩策略安装使用文档](docs/主板趋势回踩策略安装使用文档.md)
- [全市场趋势回踩策略说明](docs/a-share-strategy-allmarket-multi-swing-defensive.md)
- [模拟仓安装使用文档](docs/模拟仓安装使用文档.md)
- [主板趋势回踩策略与模拟仓联动案例](docs/主板趋势回踩策略与模拟仓联动案例.md)

## 其他 Skill

- `macd-second-golden-cross`
  - 适合判断“MACD 底背离 + 零轴下二次金叉”这类修复型机会

- `macd-trend-resonance-stock-picker`
  - 适合做“均线定方向，MACD 定节奏”的趋势共振选股

- `tuige-shortline-trading`
  - 适合按短线场景做 trigger / invalidation / risk / position_grade 判断

## 参考

- Cursor: [Agent Skills](https://www.trycursor.com/docs/context/skills)
- Claude Code: [Extend Claude with skills](https://code.claude.com/docs/en/skills.md)
- Codex: [Agent Skills](https://developers.openai.com/codex/skills)
- Qoder: [Skills](https://docs.qoder.com/extensions/skills)
