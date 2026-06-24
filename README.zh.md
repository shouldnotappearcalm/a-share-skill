# a-share-skill

> English README: [README.md](README.md)

面向 AI 工具的 A 股数据分析与模拟交易 skill 集合，适合 stock analysis、quant trading、paper trading、A-share workflow：

- `a-share-data`：数据查询与分析
- `a-share-paper-trading`：模拟盘执行与回测

你可以直接让 AI：

- 查个股实时行情、历史走势、技术指标、事件和行业信息
- 创建 `calm1` 模拟账户，查看账户详情、全部交易记录并下模拟单
- 结合大盘、持仓和账户状态，判断今天该买、卖、持有还是不动

## 趋势回踩策略说明

`a-share-strategy-mainboard-multi-swing-defensive`（主板趋势回踩）和 `a-share-strategy-allmarket-multi-swing-defensive`（全市场趋势回踩）**暂不对外公开**。

想了解每日操作思路、候选扫描和持仓管理，可以关注下方小红书账号，我会在那里持续更新。

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

## 两个核心 Skill

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
- `管模拟盘`：用 `a-share-paper-trading` 创建 `calm1`，初始资金 `1000000`，再查看 `calm1` 账户详情和全部交易记录。

## 组合使用

- `数据分析`
  - `a-share-data`
  - 适合做单票分析、市场状态观察和批量拉数

- `模拟执行`
  - `a-share-data + a-share-paper-trading`
  - 适合先拉数据做判断，再在 `calm1` 上执行模拟买卖

## 安装

以下示例包含两个核心 skill：`a-share-data`、`a-share-paper-trading`。

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

如果你用的是 OpenCode、openclaw 或其他支持 skills 的 AI 工具，只需要把路径替换成对应工具的 skills 目录。

## 文档导航

- [A股数据安装使用文档](docs/A股数据安装使用文档.md)
- [模拟仓安装使用文档](docs/模拟仓安装使用文档.md)

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
