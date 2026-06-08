# MiniClaw 文件优先长期记忆系统

MiniClaw 的长期记忆采用文件优先设计：Markdown 是唯一权威来源，SQLite 只保存可重建的检索索引。Agent 像操作项目文件一样管理记忆：先搜索，再读取精确行范围，最后写入或精确编辑。

## 存储布局

默认目录由 `MINICLAW_MEMORY_DIR` 配置，默认是 `backend/memories/`：

```text
backend/memories/
├─ memory.sqlite
└─ memory/
   ├─ MEMORY.md          # 长期事实、决策、主题索引
   ├─ USER.md            # 用户画像、偏好、稳定个人信息
   ├─ YYYY-MM-DD.md      # 每日记录
   └─ topics/
      └─ <topic>.md      # 主题级长期记忆
```

支持的安全路径只有：

```text
memory/MEMORY.md
memory/USER.md
memory/YYYY-MM-DD.md
memory/topics/<topic>.md
```

绝对路径、目录穿越、非 Markdown 文件和非 `memory/` 路径都会被拒绝。

## 工具

### `memory_search`

搜索长期记忆 Markdown 文件。搜索前会同步 dirty 或手动变更的 Markdown 文件到 SQLite。

返回结果包含行号引用：

```json
{
  "path": "memory/USER.md",
  "citation": "memory/USER.md#L3-L8",
  "startLine": 3,
  "endLine": 8,
  "snippet": "...",
  "score": 0.82,
  "source": "memory",
  "matchType": "hybrid"
}
```

### `memory_get`

按安全路径读取完整文件或指定行范围。Agent 应在编辑前先调用此工具确认 exact text。

### `memory_write`

写入或追加 Markdown。该工具只修改 Markdown 并标记 dirty，不直接写 SQLite 检索行。

### `memory_edit`

用 `oldText` / `newText` 做精确替换。`oldText` 不存在或出现多次都会失败，避免错误修改长期记忆。

### `memory_reindex`

从 Markdown 全量重建 SQLite 索引。适用于手动编辑后修复索引或排查搜索异常。

### 兼容别名

旧工具 `remember`、`search_memory`、`read_memory`、`forget_memory`、`reindex_memories` 仍作为兼容别名保留。新调用应优先使用 `memory_*` 文件式工具。

## SQLite 索引

SQLite 保存：

```text
memory_files       path/source/hash/mtime/size
memory_chunks      path/source/start_line/end_line/content/content_hash
memory_fts         FTS5 检索文本
memory_embeddings  可选向量 blob
```

工具写入和编辑不会直接维护这些索引行。索引由同步层从 Markdown 更新：

```text
memory_write/edit
    │
    ├─ 修改 Markdown
    └─ mark dirty

memory_search
    │
    ├─ sync dirty/changed files
    └─ query SQLite
```

## 检索模式

- `fts`：SQLite FTS5，中文内容会生成 bigram 检索文本。
- `vector`：需要 embedding 配置，使用 SQLite blob 中的向量做 cosine similarity。
- `hybrid`：embedding 可用时合并 FTS/vector；不可用时降级为 FTS 并返回 warning。

## 稳定记忆注入

上下文准备阶段可以把稳定记忆作为 system context 注入模型请求。默认只读取：

```text
memory/USER.md
memory/MEMORY.md
```

配置：

```text
MINICLAW_MEMORY_PROMPT_ENABLED=true
MINICLAW_MEMORY_PROMPT_MAX_CHARS=12000
```

每日文件和主题文件不会整篇自动注入，仍通过 `memory_search` / `memory_get` 按需召回。
