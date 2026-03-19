# TODOS

## Phase 4-5: 知识图谱 + 智能层
**What:** 实体关联图谱、关系网络、模式识别、巧合引擎、智能提醒
**Why:** CEO Review 扩展项 1-7 的实现。把"存储+蒸馏"升级为"理解+主动发现"。
**Pros:** 从笔记工具变成真正的"AI参谋"。compounding value 的核心。
**Cons:** 依赖实体消歧质量，可能产生错误关联。需要足够数据量才有意义。
**Context:** CEO Review (2026-03-19) 中 7 个扩展全部 ACCEPTED：知识图谱、时间线模式识别、关系网络、主动洞察引擎、照片深度理解(已纳入当前scope)、巧合引擎、智能提醒。需要多源数据导入(Get笔记+微信+照片)跑通后才能有效实现跨源关联。
**Effort:** L (human) → M (CC ~3-4小时)
**Priority:** P2
**Depends on:** Phase 1-3 数据导入完成，有足够数据量验证关联质量

## 文件系统索引层
**What:** 当知识库 >5000 条目时，加 SQLite FTS5 全文搜索索引
**Why:** 文件 grep 在大数据量下变慢（预计 3-10s for 5000 files）
**Pros:** 查询从秒级降到毫秒级，支持更复杂的搜索（模糊、组合）
**Cons:** 引入双写（文件+索引），需要保持同步
**Context:** 当前 MVP 用文件 grep 搜索，性能在 <1000 条目内完全够用。SQLite 已经在项目中（sync-state.db），加 FTS5 索引是自然扩展。
**Effort:** M (human) → S (CC ~30min)
**Priority:** P3
**Depends on:** 数据量增长到 ~5000 条目（预计 6-12个月）
