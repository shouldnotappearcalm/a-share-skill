# a-share-skill

面向 AI 工具的 A 股 skill 集合，核心覆盖三层能力：

- `a-share-data`：数据查询与分析
- `a-share-strategy-mainboard-multi-swing-defensive`：主板趋势回踩信号
- `a-share-paper-trading`：模拟盘执行与回测

你可以直接让 AI：

- 查个股实时行情、历史走势、技术指标、事件和行业信息
- 扫描主板候选，输出买入参考和持仓卖出参考
- 创建 `calm1` 模拟账户，查看账户详情、全部交易记录并下模拟单
- 结合大盘、候选、持仓和账户状态，判断今天该买、卖、持有还是不动

## 交流群

<img width="400" alt="39afc5617ddc27f26af912496edd3d34" src="https://github.com/user-attachments/assets/46d48fbf-6a9e-4d34-9966-0df52fe06a86" />

## 模拟仓一个半月 32 个点收益

<table>
  <tr>
    <td align="center" valign="top">
      <strong>4.16 初始化账户100w</strong><br/><br/>
      <img width="240" alt="7259c3d33aca6e81f948d90f89be5d15" src="https://github.com/user-attachments/assets/ef7d9b23-b9a3-4c49-afc2-3f81fd489058" />
    </td>
    <td align="center" valign="top">
      <strong>6.5 盘中 132w（持续更新中）</strong><br/>
      当前持仓：鹏鼎控股、华电辽能、太极实业、晶方科技<br/><br/>
      <img width="240" alt="510dc971161e47e91114bdf1a0cab2a7" src="https://github.com/user-attachments/assets/1a37359b-b7cf-4beb-b882-d44a452d3130" />
      <img width="240" alt="10a8b5bbfa7bbaba2ca2a9fc1b8aa98c" src="https://github.com/user-attachments/assets/cfb14495-7a46-4656-be20-d1e9779a9093" />
    </td>
  </tr>
</table>

## 三个核心 Skill

### `a-share-data`

适合问：

- 这只票现在怎么样
- 最近 60 天走势怎样
- 有没有事件驱动
- 沪深300、热点板块、北向资金现在怎么样

能做：

- 实时行情、历史 K 线、技术指标、事件、行业、指数与宏观数据

文档：

- [docs/a-share-data-ai-usage.md](docs/a-share-data-ai-usage.md)

### `a-share-strategy-mainboard-multi-swing-defensive`

适合问：

- 今天有哪些主板候选
- 我的持仓要不要卖
- 今天更适合买新票还是偏防守

能做：

- 主板池扫描、买入参考、卖出参考、批量现价快照

文档：

- [docs/a-share-strategy-mainboard-multi-swing-defensive-ai-usage.md](docs/a-share-strategy-mainboard-multi-swing-defensive-ai-usage.md)

### `a-share-paper-trading`

适合问：

- 给 `calm1` 创建模拟账户
- 看 `calm1` 账户详情、持仓、订单、全部交易记录
- 给 `calm1` 下模拟买单或卖单
- 跑简单回测

能做：

- 账户管理、下单、撤单、持仓、订单、成交、账户估值、回测

文档：

- [docs/a-share-paper-trading-ai-usage.md](docs/a-share-paper-trading-ai-usage.md)

## 最短案例

- `查数据`：用 `a-share-data` 看 600519 最新行情、最近 60 日日线和 MACD。
- `跑策略`：用 `a-share-strategy-mainboard-multi-swing-defensive` 扫今天主板候选，只看最终过滤结果。
- `管模拟盘`：用 `a-share-paper-trading` 创建 `calm1`，初始资金 `1000000`，再查看 `calm1` 账户详情和全部交易记录。
- `组合工作流`：先扫候选，再结合大盘和 `calm1` 持仓，判断今天该买、卖、持有还是不动。

## 组合使用

- `数据分析`
  - `a-share-data`
  - 适合做单票分析、市场状态观察和批量拉数

- `策略判断`
  - `a-share-data + a-share-strategy-mainboard-multi-swing-defensive`
  - 适合做候选扫描、持仓卖出参考和环境判断

- `模拟执行闭环`
  - `a-share-strategy-mainboard-multi-swing-defensive + a-share-paper-trading`
  - 适合让 AI 先分析，再决定是否给 `calm1` 买入、卖出、减仓或不交易

详细案例：

- [docs/a-share-strategy-mainboard-multi-swing-defensive-paper-trading-workflow.md](docs/a-share-strategy-mainboard-multi-swing-defensive-paper-trading-workflow.md)

## 安装

以下示例只保留三个核心 skill：`a-share-data`、`a-share-strategy-mainboard-multi-swing-defensive`、`a-share-paper-trading`。

### Codex

```bash
mkdir -p ~/.agents/skills
cp -R a-share-data ~/.agents/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.agents/skills/
cp -R a-share-paper-trading ~/.agents/skills/
```

### Cursor

```bash
mkdir -p ~/.cursor/skills
cp -R a-share-data ~/.cursor/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.cursor/skills/
cp -R a-share-paper-trading ~/.cursor/skills/
```

### Claude Code

```bash
mkdir -p ~/.claude/skills
cp -R a-share-data ~/.claude/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.claude/skills/
cp -R a-share-paper-trading ~/.claude/skills/
```

### Qoder

```bash
mkdir -p ~/.qoder/skills
cp -R a-share-data ~/.qoder/skills/
cp -R a-share-strategy-mainboard-multi-swing-defensive ~/.qoder/skills/
cp -R a-share-paper-trading ~/.qoder/skills/
```

如果你用的是 OpenCode、openclaw 或其他支持 skills 的 AI 工具，只需要把路径替换成对应工具的 skills 目录。

## 文档导航

- [a-share-data 安装使用文档](docs/a-share-data-ai-usage.md)
- [a-share-strategy-mainboard-multi-swing-defensive 安装使用文档](docs/a-share-strategy-mainboard-multi-swing-defensive-ai-usage.md)
- [模拟仓（a-share-paper-trading）安装使用文档](docs/a-share-paper-trading-ai-usage.md)
- [策略 + 模拟盘组合工作流](docs/a-share-strategy-mainboard-multi-swing-defensive-paper-trading-workflow.md)

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
