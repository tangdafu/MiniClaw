# MiniClaw 记忆系统实现文档

MiniClaw 的记忆系统用于保存长期记忆，例如用户偏好、项目事实、普通笔记和可复用上下文。系统采用“双层存储”设计：Markdown 保存完整正文，SQLite 保存索引、分片、FTS 检索数据和向量数据。

## 1. 设计目标

- Markdown 是完整记忆正文的权威来源，方便人工阅读、编辑、备份和迁移。
- SQLite 是检索索引层，负责元数据、chunk、FTS、向量 blob 和删除状态。
- `search_memory` 返回相关片段，不直接返回整篇文档，避免污染模型上下文。
- `read_memory` 按 `memory_id` 返回完整 Markdown 文档。
- 支持 `fts`、`vector`、`hybrid` 三种检索模式。
- Embedding 未配置时，记忆仍可创建，FTS 仍可用，hybrid 自动降级为 FTS。

## 2. 模块结构

```text
backend/miniclaw/memory/
├─ __init__.py          # 对外导出 MemoryService、MemoryConfig、tools 等
├─ config.py            # 记忆目录和 embedding 配置
├─ models.py            # MemoryRecord、MemoryChunk、MemorySearchResult
├─ store.py             # Markdown 文件写入、读取、forget 移动到 .trash
├─ text.py              # chunk 切分、hash、FTS 文本规范化
├─ embeddings.py        # OpenAI-compatible embedding、fake embedding、向量编解码
├─ index.py             # SQLite schema、索引、FTS/vector 查询
├─ service.py           # 记忆生命周期和检索编排
└─ tools.py             # remember/search_memory/read_memory/forget_memory/reindex_memories 工具
```

工具注册入口：

```text
backend/miniclaw/tools/registry.py
```

`get_builtin_tools()` 会创建 `MemoryService` 并注册记忆工具。

## 3. 存储布局

默认目录：

```text
backend/memories/
├─ memory.sqlite
├─ profile/
│  └─ user.md
├─ memory/
│  └─ <topic>.md
├─ daily/
│  └─ YYYY-MM-DD.md
└─ .trash/
```

`MINICLAW_MEMORY_DIR` 可覆盖默认目录。

记忆按 scope 写入固定或主题级 Markdown 文档：

```text
profile/user.md        用户稳定偏好、身份信息、长期工作习惯
memory/<topic>.md      主题级长期事实、项目知识、普通笔记
daily/YYYY-MM-DD.md    当天摘要和阶段性上下文
```

旧的 `preference` 类型会归一为 `profile`，旧的 `project`/`note` 类型会归一为 `memory`。

Markdown 文件格式：

```md
---
id: profile_user
type: profile
title: 用户前端偏好
tags:
  - frontend
  - design
source: user_explicit
confidence: 0.9
created_at: 2026-06-02T01:20:00+00:00
updated_at: 2026-06-02T01:20:00+00:00
content_hash: <sha256>
---

用户不喜欢普通、平均、模板化的前端界面。
```

## 4. SQLite Schema

SQLite 文件：

```text
backend/memories/memory.sqlite
```

### `memories`

保存记忆文档级元数据。

```text
id            TEXT PRIMARY KEY
path          TEXT NOT NULL
type          TEXT NOT NULL
source        TEXT NOT NULL
confidence    REAL NOT NULL
created_at    TEXT NOT NULL
updated_at    TEXT NOT NULL
deleted_at    TEXT
content_hash  TEXT NOT NULL
```

### `memory_chunks`

保存每条记忆正文切分后的片段和片段在 Markdown 正文中的位置。

```text
id            TEXT PRIMARY KEY
memory_id     TEXT NOT NULL
chunk_index   INTEGER NOT NULL
start_char    INTEGER NOT NULL
end_char      INTEGER NOT NULL
content       TEXT NOT NULL
content_hash  TEXT NOT NULL
```

chunk 到 Markdown 的映射关系：

```text
memory_chunks.memory_id → memories.id
memories.path           → Markdown 文件路径
start_char/end_char     → Markdown 正文中的片段位置
```

### `memory_embeddings`

保存 chunk 向量。

```text
chunk_id     TEXT NOT NULL
model        TEXT NOT NULL
dimension    INTEGER NOT NULL
vector_blob  BLOB NOT NULL
PRIMARY KEY(chunk_id, model)
```

向量以 float32 小端序二进制 blob 存储。

### `memory_fts`

SQLite FTS5 虚拟表，用于关键词检索。

```text
chunk_id    UNINDEXED
memory_id   UNINDEXED
title
search_text
```

`search_text` 是规范化后的检索文本，不是原文。检索结果会 join 回 `memory_chunks.content` 返回原始片段。

## 5. 写入流程

调用 `remember` 后：

```text
remember(title, content, memory_type, topic, memory_date, tags)
        │
        ▼
根据 scope 解析 Markdown 路径和 memory_id
        │
        ├─ profile → profile/user.md        → profile_user
        ├─ memory  → memory/<topic>.md      → memory_<topic>
        └─ daily   → daily/YYYY-MM-DD.md    → daily_YYYY_MM_DD
        │
        ▼
写入或合并 Markdown 文件，重复 content 不再次追加
        │
        ▼
正文切 chunk
        │
        ▼
生成 FTS search_text
        │
        ├─ content_hash 未变化：跳过重建索引
        ├─ embedding 可用且成功：生成 chunk 向量
        └─ embedding 不可用或失败：跳过向量，仍写入 FTS 索引
        │
        ▼
SQLite transaction 写入 metadata/chunks/fts/embeddings
```

写入同一 scoped 文档时，Markdown 文件会先作为权威正文被读取和合并；如果合并后的 `content_hash` 与 SQLite 中当前 active 记录一致，系统会跳过 chunk、FTS 和 embedding 重建。

如果 Markdown 已被人工编辑或 SQLite 索引损坏，可调用 `reindex_memories` 从 Markdown 重新生成 SQLite metadata、chunk、FTS 和可用的 embedding 向量。

## 6. 检索模式

`search_memory` 支持三种模式：

```text
mode = fts      只走 SQLite FTS
mode = vector   只走向量检索
mode = hybrid   FTS + vector 合并，默认推荐
```

### FTS 检索

FTS 使用 SQLite FTS5。

中文没有空格，默认 tokenizer 效果弱，因此系统会生成中文 bigram：

```text
原文：用户希望前端界面更精致
search_text：用户 户希 希望 前端 端界 界面 面更 更精 精致
```

查询也会做同样规范化：

```text
query：前端界面
normalized：前端 端界 界面
```

然后执行 FTS MATCH，返回 chunk 级结果。

### Vector 检索

Vector 检索需要配置 embedding：

```text
MINICLAW_EMBEDDING_MODEL
MINICLAW_EMBEDDING_BASE_URL
MINICLAW_EMBEDDING_API_KEY
```

流程：

```text
query
  │
  ▼
embedding provider 生成 query vector
  │
  ▼
SQLite 读取 chunk vector_blob
  │
  ▼
Python cosine similarity
  │
  ▼
按 score 排序返回 chunk
```

如果未配置 embedding，`vector` 模式返回明确不可用提示。

如果 embedding 服务在记忆写入或重建索引时失败，系统会跳过向量写入并继续保存 Markdown、metadata、chunk 和 FTS 索引，避免外部 embedding 服务影响核心记忆能力。

### Hybrid 检索

Hybrid 会同时执行 FTS 和 vector：

```text
FTS top-k      Vector top-k
    │               │
    └──────┬────────┘
           ▼
      按 chunk_id 合并
           │
           ▼
      合并 score、排序，并按 memory_id 去重
```

当前合并权重：

```text
fts_score    * 0.4
vector_score * 0.6
```

Embedding 不可用时，hybrid 会降级为 FTS，并在结果里返回 warning。

FTS、vector 和 hybrid 的最终结果都会按 `memory_id` 去重，避免同一个大型 topic 文档的多个 chunk 挤掉其他相关记忆。空查询会返回 `empty search query` warning。

## 7. 工具接口

### `remember`

保存一条长期记忆。

参数：

```json
{
  "title": "用户前端偏好",
  "content": "用户不喜欢普通模板化前端界面。",
  "memory_type": "profile",
  "topic": null,
  "memory_date": null,
  "tags": ["frontend", "design"],
  "source": "user_explicit",
  "confidence": 0.9
}
```

`memory_type` 支持：

| 类型 | 写入位置 | 适用场景 |
|------|----------|----------|
| `profile` | `profile/user.md` | 用户稳定偏好、身份、工作习惯 |
| `memory` | `memory/<topic>.md` | 主题级长期事实、项目知识、笔记 |
| `daily` | `daily/YYYY-MM-DD.md` | 当日摘要、阶段性上下文 |

如果相同正文已经存在于目标 Markdown 中，系统不会重复追加。更新同一个 scoped 文档时，`created_at` 保留首次创建时间，`updated_at` 记录本次写入时间。后续追加会使用语义化小节标题：`Profile Update`、`Topic Update` 或 `Daily Entry`。

返回：

```json
{
  "memory_id": "profile_user",
  "path": "profile/user.md",
  "title": "用户前端偏好",
  "type": "profile",
  "tags": ["frontend", "design"],
  "read_hint": "Use read_memory('profile_user') to read the full Markdown document."
}
```

### `search_memory`

搜索长期记忆，返回 chunk 片段。

参数：

```json
{
  "query": "前端界面偏好",
  "mode": "hybrid",
  "memory_type": "profile",
  "limit": 5
}
```

返回：

```json
{
  "warning": null,
  "results": [
    {
      "memory_id": "profile_user",
      "chunk_id": "profile_user_chunk_0",
      "path": "profile/user.md",
      "title": "用户前端偏好",
      "type": "profile",
      "document_scope": "profile",
      "tags": ["frontend", "design"],
      "score": 0.86,
      "match_type": "hybrid",
      "chunk_index": 0,
      "start_char": 0,
      "end_char": 128,
      "excerpt": "用户不喜欢普通模板化前端界面。",
      "read_hint": "Use read_memory('profile_user') to read the full Markdown document."
    }
  ]
}
```

### `read_memory`

按 `memory_id` 读取完整 Markdown。

```json
{
  "memory_id": "profile_user"
}
```

### `forget_memory`

遗忘整个 scoped Markdown 记忆文档，使其不再出现在检索结果中。

```json
{
  "memory_id": "profile_user"
}
```

当前实现会把 Markdown 文件移动到 `.trash/`，并在 SQLite 中设置 `deleted_at`。注意，`profile_user` 表示整个 `profile/user.md`，`memory_<topic>` 表示整个主题文件，不是删除单个 bullet。

### `reindex_memories`

从 Markdown 权威文件重建 SQLite 索引，适用于用户手动编辑 Markdown、SQLite 索引损坏或需要恢复索引的场景。`.trash/` 下的已删除记忆不会被重新索引。

返回：

```json
{
  "indexed": 3,
  "skipped": 0,
  "errors": []
}
```

## 8. 配置

`.env.example` 中的相关配置：

```text
MINICLAW_MEMORY_DIR=memories

MINICLAW_EMBEDDING_MODEL=
MINICLAW_EMBEDDING_BASE_URL=
MINICLAW_EMBEDDING_API_KEY=
```

如果 embedding 变量为空：

```text
remember      可用
read_memory   可用
forget_memory 可用
fts           可用
vector        不可用，返回 warning/error
hybrid        降级为 fts
```

## 9. 当前限制

- V1 不会自动从每轮聊天中提取记忆，只有模型调用 `remember` 时才写入。
- V1 不会自动把相关记忆注入每次模型上下文，模型需要主动调用 `search_memory`。
- V1 使用 Python cosine similarity，不依赖 `sqlite-vec` 或 `sqlite-vss`。
- Markdown 被用户手动编辑后，SQLite 索引不会自动重建；需要手动调用 `reindex_memories`。
- 当前没有前端记忆管理 UI。
- 当前 frontmatter parser 只支持本系统渲染的有限 YAML-like 格式，不是完整 YAML 解析器。

## 10. 测试

相关测试文件：

```text
backend/test_memory_system.py
```

覆盖：

- Markdown 创建、读取、遗忘。
- SQLite schema 初始化。
- chunk 位置映射。
- 中文 bigram FTS 检索。
- fake embedding vector 检索。
- vector 不可用时的错误提示。
- embedding 写入失败时降级为 Markdown + FTS。
- hybrid 降级。
- scoped 文档去重、`content_hash` 未变化跳过索引重建。
- `reindex_memories` 从 Markdown 重建索引。
- 工具注册和工具输出格式。

运行：

```bash
uv run pytest test_memory_system.py
```

完整后端回归：

```bash
uv run pytest test_memory_system.py test_system_prompt.py test_file_tools.py test_context_assembler.py test_react_runtime.py test_session_history.py
```
