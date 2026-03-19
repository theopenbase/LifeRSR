# CLAUDE.md

## 项目概览

**LifeRSR** — Real to Simulation to Real (real2sim2real)
Agent-Native 个人知识库 / AI 参谋知识库 / Digital Twin

核心理念：真实生活数据 → AI 蒸馏成结构化知识 → 反哺真实决策
主要消费者不是人类 UI，而是 AI Agent（Claude Code）。

GitHub: https://github.com/theopenbase/LifeRSR

## 架构

```
数据源                    收件箱              AI 蒸馏            知识库
┌──────────┐  recall   ┌──────────┐  distill  ┌────────────┐
│ Get笔记  │ ────────▶ │ inbox/   │ ────────▶ │ knowledge/ │ (高置信度)
│ biji.com │           │ getnote/ │           ├────────────┤
└──────────┘           │ wechat/  │           │ staging/   │ (中/低置信度)
┌──────────┐  ingest   │ photo/   │           └────────────┘
│ 微信聊天 │ ────────▶ └──────────┘              │ review
│ 照片截图 │                                     ▼
└──────────┘                                 approve / reject
```

关键设计决策：
- **biji.com API 是搜索型**（非导出型），无"列出全部笔记"接口。采用 MCP + 本地缓存模式：查询累积
- **文件存内容，SQLite 管状态**：笔记用 YAML frontmatter + Markdown，同步去重用 data/.state.db
- **Claude 自评置信度**：high → knowledge/，medium/low → staging/ 待人工审核
- **稳定 ID**：WeChat 用内容 hash `wechat-{sha256[:12]}`，Photo 用文件 hash `photo-{sha256[:12]}`

## 技术栈

- Python 3.11+, click CLI, anthropic SDK, httpx, python-frontmatter, rich
- 测试：pytest（92 tests passing）
- 入口命令：`kb`（定义在 pyproject.toml [project.scripts]）

## 文件结构

```
src/
├── cli.py        — CLI 入口：kb recall/ingest/distill/review/query/status
├── getnote.py    — Get笔记 recall API 客户端 + SyncState (SQLite)
├── store.py      — Note 数据结构 + Markdown 文件读写 (save/load/list/query/move)
├── distill.py    — Claude API 蒸馏 (分类/标签/摘要/实体抽取/置信度)
├── staging.py    — 审核工作流 (pending/approve/reject/approve_all)
├── wechat.py     — 微信聊天解析 (3种格式: 时间戳/冒号/fallback)
└── photo.py      — 照片理解 via Claude Vision (OCR + 场景描述)

tests/
├── test_getnote.py      — 16 tests
├── test_store.py        — 22 tests
├── test_distill.py      — 9 tests
├── test_staging.py      — 9 tests
├── test_wechat.py       — 11 tests
├── test_photo.py        — 18 tests
└── test_integration.py  — 7 tests

docs/designs/
└── personal-knowledge-base.md  — 完整系统设计文档 (CEO plan promoted)
```

## CLI 命令

```bash
kb recall "AI教育"           # 从 Get笔记 搜索并缓存到 inbox/getnote/
kb ingest chat.txt -s wechat  # 导入微信聊天到 inbox/wechat/
kb ingest photo.jpg           # 导入照片到 inbox/photo/ (自动识别)
kb distill --all              # AI 蒸馏全部 inbox → knowledge/ 或 staging/
kb review                     # 交互审核 staging/ 中的笔记
kb review --approve-all       # 批量通过全部 staging
kb query "关键词"             # 搜索 knowledge/
kb status                     # 查看统计信息
```

## 环境配置

```bash
cp .env.example .env
# 填入：GET_BIJI_API_KEY, GET_BIJI_TOPIC_ID, ANTHROPIC_API_KEY
```

## 开发命令

```bash
source .venv/bin/activate
pip install -e ".[dev]"
pytest tests/ -v              # 运行全部测试
```

## 开发历程

### 2026-03-19: 项目初始化 (v0.1.0)

**规划阶段：**
1. `/plan-ceo-review` — 定义产品愿景，7 项扩展全部采纳（知识图谱、时间线、关系网络、主动洞察、照片理解、巧合引擎、智能提醒）
2. `/office-hours` — 验证 startup idea，锁定 MVP 切入点："Get笔记 → AI 蒸馏"，选择 Approach B（AI 参谋知识库）
3. `/plan-eng-review` — 锁定实现：7 源文件、Python 技术栈、SQLite 状态管理、Claude 置信度分流

**关键发现：**
- biji.com API spike：只有搜索接口，无全量导出 → 改为 MCP + 本地缓存模式
- 用户选择 SQLite 管状态（而非 JSON），放松了纯文件系统约束

**实现阶段：**
- 完成全部 7 个源模块 + 7 个测试文件（92 tests passing）
- 创建 GitHub repo: theopenbase/LifeRSR
- 初始提交 + 推送

**待办：** 见 TODOS.md（Phase 4-5 知识图谱 + 智能层，SQLite FTS5 索引层）

## 相关文件（项目外）

- `~/.gstack/projects/theopenbase/ceo-plans/` — CEO plan 原始记录
- `~/.gstack/projects/theopenbase/feishufang-unknown-design-*.md` — Office hours 设计文档
- `~/.gstack/projects/theopenbase/feishufang-master-test-plan-*.md` — 测试计划

## gstack

Use the `/browse` skill from gstack for all web browsing. Never use `mcp__Claude_in_Chrome__*` tools.

### Troubleshooting

If gstack skills aren't working, run `cd .claude/skills/gstack && ./setup` to build the binary and register skills.
