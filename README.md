# a-share-skill

这是一个基于 **Cursor Skill** 的 A 股数据技能包目录，约定结构为：

```bash
a-share-skill/
  README.md
  skills/
    a-share-skill/
      SKILL.md
      scripts/
      references/
```

当前仅包含一个 skill：`a-share-skill`，具体说明见 `skills/a-share-skill/SKILL.md`。

- `scripts/`：可执行脚本（实时数据、历史/财务、技术指标），供 Agent 调用
- `references/`：补充说明文档，例如 `api-reference.md`

你可以：
- 将整个 `skills/a-share-skill` 目录打包，放入 `~/.cursor/skills/` 或项目 `.cursor/skills/` 中使用
- 在此目录下继续追加更多 Skills（例如 `skills/xxx-skill/`）
