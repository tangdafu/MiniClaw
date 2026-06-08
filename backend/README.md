# MiniClaw 后端架构与运行逻辑

MiniClaw 后端是一个 FastAPI 应用，负责接收前端 WebSocket 消息、调用 OpenAI 兼容 Chat Completions API、执行本地工具，并将完整对话历史持久化为 JSON 文件。

## 1. 启动方式

后端使用 `uv` 管理依赖。从 `backend/` 目录运行：

```bash
uv sync
uv run python main.py
```

服务默认监听 `http://localhost:8000`，主要接口：

| 接口 | 说明 |
|------|------|
| `GET /health` | 返回后端健康状态、Claw 是否初始化、工具数量 |
| `WebSocket /ws/chat` | 聊天入口，接收用户消息并流式返回 Agent 事件 |

环境变量从 `backend/.env` 加载：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI 兼容 API Key |
| `OPENAI_BASE_URL` | OpenAI 兼容 API Base URL |
| `OPENAI_MODEL` | 模型名称，未设置时默认 `gpt-4o` |
| `MINICLAW_CONTEXT_COMPACT_TRIGGER_TOKENS` | 估算输入 token 超过该值时触发上下文压缩，默认 `180000` |
| `MINICLAW_CONTEXT_COMPACT_TARGET_TOKENS` | 压缩后模型上下文目标估算 token，默认 `90000` |
| `MINICLAW_CONTEXT_SUMMARY_TARGET_TOKENS` | 为摘要预留的估算 token，默认 `8000` |
| `MINICLAW_CONTEXT_COMPRESSION_MODEL` | 可选摘要压缩模型；未设置时使用聊天模型 |
| `MINICLAW_MEMORY_DIR` | 长期记忆目录，默认 `backend/memories` |
| `MINICLAW_EMBEDDING_MODEL` | 可选 Embedding 模型；未设置时 vector 搜索不可用 |
| `MINICLAW_EMBEDDING_BASE_URL` | 可选 Embedding API Base URL |
| `MINICLAW_EMBEDDING_API_KEY` | 可选 Embedding API Key |

## 2. 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│                         main.py                             │
│  FastAPI 入口、WebSocket 接口、应用生命周期、全局 Claw 注入   │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    miniclaw/claw.py                         │
│  Claw：会话生命周期、消息加载/保存、Agent 调用编排            │
│  SessionManager：基于文件系统的 chat.json 持久化              │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                    miniclaw/agent.py                        │
│  Agent：稳定门面，保留 chat(messages, user_message) 接口      │
│  AgentConfig：模型、API Key、Base URL、迭代次数、系统提示配置 │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                 miniclaw/react_runtime.py                   │
│  ReactRuntime：真正执行 ReAct 多轮循环                       │
│  - 构建模型请求                                              │
│  - 读取流式响应                                              │
│  - 输出 Event                                                │
│  - 协调工具执行                                              │
│  - 原地更新 messages                                         │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
                ▼                               ▼
┌──────────────────────────────┐   ┌──────────────────────────┐
│      miniclaw/stream.py      │   │ miniclaw/tool_executor.py│
│  StreamAccumulator            │   │ ToolExecutor             │
│  - 累积文本和 reasoning       │   │ - 查找工具                │
│  - 重建 OpenAI tool_calls     │   │ - 解析 JSON 参数          │
└──────────────────────────────┘   │ - 调用同步/异步 handler   │
                                   └──────────────────────────┘
```

## 3. 核心模块职责

| 文件 | 职责 |
|------|------|
| `main.py` | FastAPI 应用入口；启动时初始化 `Agent`、工具列表和全局 `Claw`；提供 `/ws/chat` 和 `/health` |
| `tools.py` | 兼容入口；保留 `get_tools()`、`SkillManager`、`execute_command` 导出，并委托 `miniclaw.tools` 内部模块 |
| `miniclaw/claw.py` | 会话编排层；负责创建会话、加载历史、调用 Agent、保存完整消息历史 |
| `miniclaw/agent.py` | Agent 门面；负责持有 OpenAI 客户端和配置，并委托 `ReactRuntime` |
| `miniclaw/react_runtime.py` | ReAct Runtime 主循环；负责模型调用、工具调用协调、事件输出、消息历史追加 |
| `miniclaw/react_context.py` | Runtime 内部数据结构，包括 `ReactContext`、`ModelRequest`、`ModelTurn`、`ToolExecution` |
| `miniclaw/stream.py` | 流式响应累积器；把模型增量 delta 还原成完整 assistant 消息和 `tool_calls` |
| `miniclaw/tool_executor.py` | 工具执行器；处理工具查找、参数 JSON 解析、同步/异步调用和错误转换 |
| `miniclaw/tools/registry.py` | 内置工具注册；组合 Skill 工具和命令工具，返回平铺的 `list[Tool]` |
| `miniclaw/tools/skills.py` | Skill 工具模块；提供 `SkillRepository` 索引、Skill 列表、文件读取和文件树输出 |
| `miniclaw/tools/command.py` | 命令工具模块；提供 `CommandRunner` 和 `execute_command` 工具注册 |
| `miniclaw/hooks.py` | Hook 生命周期；为未来的记忆、路由、审计、压缩等功能提供扩展点 |
| `miniclaw/types.py` | Pydantic 类型定义，包括 `Message`、`Tool`、`Event` |

## 4. WebSocket 协议

前端发送聊天命令。旧格式仍兼容：

```json
{
  "session_id": "",
  "message": "你好"
}
```

推荐命令格式：

```json
{
  "type": "chat",
  "session_id": "<session_id>",
  "message": "你好"
}
```

运行控制命令：

```json
{ "type": "cancel_current", "session_id": "<session_id>" }
{ "type": "clear_queue", "session_id": "<session_id>" }
{ "type": "stop_session", "session_id": "<session_id>" }
```

`Claw` 为每个 session 维护一个内存优先级 FIFO 队列。同一个 session 一次只执行一个 run，后续命令排队；不同 session 可以并发执行。

后端返回一组流式事件：

| 事件类型 | 字段 | 说明 |
|----------|------|------|
| `session_created` | `session_id` | 后端创建新会话时返回 |
| `queued` | `session_id`, `run_id`, `queue_position`, `queued_count` | 聊天命令已加入队列 |
| `run_started` | `session_id`, `run_id` | queued job 开始执行 |
| `queue_updated` | `session_id`, `running_run_id`, `queued_count` | 队列或运行状态变化 |
| `text` | `session_id`, `run_id`, `content` | 模型正文增量 |
| `reasoning` | `session_id`, `run_id`, `content` | 模型 reasoning 增量，适用于支持该字段的模型 |
| `tool_call` | `session_id`, `run_id`, `name`, `arguments` | Runtime 即将展示的工具调用 |
| `tool_result` | `session_id`, `run_id`, `name`, `result` | 工具执行结果 |
| `done` | `session_id`, `run_id` | 当前 run 完成 |
| `cancelled` | `session_id`, `run_id` | 当前 run 被取消 |
| `queue_cleared` | `session_id`, `cleared_count` | 未开始的 queued jobs 已清空 |
| `session_stopped` | `session_id`, `cleared_count` | 当前 run 被取消且队列已清空 |
| `error` | `error` | 错误信息。内部字段名为 `error_msg`，序列化时映射为 `error` |

## 5. 一次对话的完整流程

```text
用户输入一个或多个命令
  │
  ▼
前端 ChatView.vue
  │  WebSocket 发送 chat / cancel_current / clear_queue / stop_session
  ▼
main.py /ws/chat
  │  receiver 接收命令，sender 发送事件
  ▼
Claw.enqueue_chat(session_id, user_message)
  │
  ├─ session_id 为空或不存在：创建新会话，emit session_created
  ├─ 创建 run_id，加入该 session 的优先级 FIFO 队列
  ├─ emit queued / queue_updated
  └─ 确保该 session worker 正在运行
        │
        ▼
session worker
  │
  ├─ 每次只取一个 queued job 执行
  ├─ 不同 session worker 可并发执行
  ├─ emit run_started
  │
  ├─ SessionManager.load_messages(session_id)
  │
  ▼
Agent.chat(messages, user_message)
  │
  ▼
ReactRuntime.run(messages, user_message)
  │
  ├─ messages.append({ role: "user", content: user_message })
  │
  ├─ 构建模型请求消息
  │
  ├─ 流式调用 OpenAI 兼容 API
  │
  ├─ StreamAccumulator 累积 text / reasoning / tool_calls
  │
  ├─ messages.append(assistant_message)
  │
  ├─ 如果存在 tool_calls：
  │  │   ├─ yield tool_call
  │  │   ├─ ToolExecutor.execute(tool_call)
  │  │   ├─ yield tool_result
  │  │   └─ messages.append({ role: "tool", ... })
  │  │
  │  └─ 如果不存在 tool_calls：yield done 并结束
  │
  ▼
Claw 保存完整 messages 到 chat.json
  │
  ▼
前端按 session_id/run_id 路由事件，渲染正文、思考过程、工具调用和队列状态
```

## 6. ReAct Runtime 循环

`ReactRuntime` 的核心特点是：模型调用、工具执行和消息持久化语义在同一个运行时上下文中完成。

关键行为：

- 用户消息会先追加到传入的 `messages` 列表。
- 每轮模型调用前会通过 `ContextCompressionService` 构建 `model_messages`，并注入可选 `system_prompt`。
- 未超过 token 触发阈值时发送完整持久化历史；超过阈值时生成摘要并保留最近完整消息尾部。
- `system_prompt` 始终位于模型请求最前面；压缩摘要作为第二条 `system` message 注入。
- 上下文压缩只影响发给模型的临时 `model_messages`，不会裁剪 `ctx.messages` 或 `chat.json` 中保存的完整历史。
- 如果保留尾部边界切到 tool 消息，压缩服务会尽量补入匹配的 assistant `tool_calls` 消息，避免产生孤立 tool 消息。
- 空字符串 `reasoning_content` 会在发给模型前移除，减少 OpenAI 兼容接口报错风险。
- 每次模型调用前都会发出 `context_usage` 事件；真正触发压缩时还会发出 `context_compression` 阶段事件。
- 模型流式返回时，正文和 reasoning 会立即转换成前端事件。
- 工具调用 delta 会先累积，等模型本轮流结束后再执行。
- 如果 assistant 发起工具调用，持久化的 assistant 消息会包含 `tool_calls` 字段，并且位于对应 `role: "tool"` 消息之前。
- 工具执行结束后进入下一轮模型调用，让模型基于工具结果继续生成最终回答。
- 如果模型不再请求工具，则输出 `done`，由 `Claw` 保存完整消息历史。

## 7. 工具系统

工具由 `miniclaw.types.Tool` 描述：

```python
Tool(
    name="execute_command",
    description="在本地终端执行一条命令并返回输出结果。",
    parameters={...},
    handler=execute_command,
)
```

`Tool.to_openai_schema()` 会把工具转换成 OpenAI function schema。Runtime 只负责协调工具调用，实际查找和执行由 `ToolExecutor` 完成。

`backend/tools.py` 是兼容入口，`main.py` 继续从这里导入 `get_tools()`。实际内置工具由 `miniclaw.tools.registry.get_builtin_tools()` 组合：

- `miniclaw.tools.skills.SkillRepository` 负责索引 `backend/skills/`，并提供 Skill 列表、文件读取和文件树输出。
- `miniclaw.tools.command.CommandRunner` 负责命令执行、工作目录、超时、输出拼接，并保留后续安全策略扩展点。
- `miniclaw.tools.files.FileTools` 负责通用文件读取、列表/glob、文本搜索、写入和精确替换。
- `miniclaw.memory.MemoryService` 负责文件优先长期记忆、Markdown 存储、SQLite 同步索引、FTS 检索和可选向量检索。

工具模块调用关系：

```text
main.py
  │
  ▼
tools.get_tools()                         # 兼容入口
  │
  ▼
miniclaw.tools.registry.get_builtin_tools()
  │
  ├─ get_skill_tools(SkillRepository)
  │    ├─ read_skill_list
  │    ├─ read_skill
  │    └─ list_skill_files
  │
  └─ get_command_tools(CommandRunner)
       └─ execute_command

  └─ get_file_tools(FileTools)
       ├─ read_file
       ├─ list_files
       ├─ search_text
       ├─ write_file
       └─ replace_text

  └─ get_memory_tools(MemoryService)
       ├─ memory_search
       ├─ memory_get
       ├─ memory_write
       ├─ memory_edit
       ├─ memory_reindex
       └─ remember/search_memory/read_memory/... # 兼容别名
```

`backend/tools.py` 还保留这些兼容导出：

| 导出 | 当前实现 |
|------|----------|
| `get_tools()` | 委托 `miniclaw.tools.registry.get_builtin_tools()` |
| `SkillManager` | `SkillRepository` 的兼容别名 |
| `execute_command()` | 创建 `CommandRunner` 并调用 `run()` |

新增内置工具时，不建议继续把实现写进 `backend/tools.py`。应在 `miniclaw/tools/` 下按领域新增模块，并由 `registry.py` 统一组合。

当前内置工具：

| 工具 | 说明 |
|------|------|
| `read_skill_list` | 列出 `backend/skills/` 下可用 Skill |
| `read_skill` | 读取指定 Skill 的 `SKILL.md` 或附属文件 |
| `list_skill_files` | 列出某个 Skill 目录下的文件结构 |
| `execute_command` | 执行本地 shell 命令，30 秒超时 |
| `read_file` | 读取本地文本文件，按行号返回，支持行数限制 |
| `list_files` | 按 glob 模式列出本地文件路径 |
| `search_text` | 在本地文本文件中搜索字符串或正则表达式 |
| `write_file` | 写入本地文本文件，会创建缺失父目录并覆盖内容 |
| `replace_text` | 对本地文本文件执行精确文本替换 |
| `memory_search` | 搜索长期记忆 Markdown 文件，返回 `path#Lx-Ly` 行号引用 |
| `memory_get` | 按安全路径和可选行范围读取记忆 Markdown |
| `memory_write` | 写入或追加安全记忆 Markdown；SQLite 由同步索引层更新 |
| `memory_edit` | 精确替换记忆文件中的唯一 `oldText`，避免追加污染 |
| `memory_reindex` | 从 Markdown 权威文件重建长期记忆 SQLite 索引 |
| `remember` / `search_memory` / `read_memory` / `forget_memory` / `reindex_memories` | 旧工具兼容别名；新调用应优先使用 `memory_*` 工具 |

通用文件工具当前不包含安全确认、权限分级或沙箱治理；这些能力会作为后续安全策略单独设计。

## 8.1 长期记忆系统

长期记忆默认存放在：

```text
backend/memories/
├─ memory.sqlite
└─ memory/
   ├─ MEMORY.md
   ├─ USER.md
   ├─ YYYY-MM-DD.md
   └─ topics/<topic>.md
```

- Markdown 文件是完整记忆正文的唯一权威来源，SQLite 只是可重建索引。
- `memory/USER.md` 保存用户画像和长期偏好，`memory/MEMORY.md` 保存高层长期事实/目录，`memory/YYYY-MM-DD.md` 保存每日记录，`memory/topics/*.md` 保存主题记忆。
- SQLite 存储文件元数据、行级 chunk、`memory_fts` 和可选 `memory_embeddings`。
- `memory_search` 会先同步 dirty/变更 Markdown，再返回 chunk 级结果，包括 `path`、`citation`、`startLine`、`endLine`、`snippet` 和 `score`。
- `memory_get(path, from_line, lines)` 按路径和行范围读取 Markdown。
- `memory_write` / `memory_edit` 只改 Markdown，不直接写检索索引；索引由 search 前同步或 `memory_reindex` 更新。
- `fts` 模式使用 SQLite FTS5，并对中文生成 bigram 检索文本。
- `vector` 模式需要配置 embedding；未配置时返回明确不可用提示。
- `hybrid` 模式在 embedding 可用时合并 FTS 和 vector 结果；不可用时降级为 FTS。
- 稳定记忆可通过上下文准备阶段注入：默认加载 `memory/USER.md` 和 `memory/MEMORY.md` 的有界内容，daily/topic 文件保持按需搜索。

## 8. Skill 系统

Skill 存放在：

```text
backend/skills/<skill-name>/SKILL.md
```

`SKILL.md` 需要包含简单 frontmatter：

```markdown
---
name: my_skill
description: 这是一个示例 Skill
---

# 使用说明
...
```

模型可以先调用 `read_skill_list` 发现 Skill，再调用 `read_skill` 读取具体指令。`SkillRepository` 会按 frontmatter 中的 `name` 建立索引，避免每次读取 Skill 时都重新扫描全部目录。

## 9. 会话持久化

会话文件结构：

```text
backend/sessions/<session_id>/chat.json
```

`SessionManager` 当前使用同步文件 IO：

- `create_session()` 创建 12 位 UUID 前缀作为会话 ID。
- `load_messages()` 读取完整 JSON 消息列表。
- `save_messages()` 在对话结束后写回完整消息列表。

由于 `Agent.chat()` / `ReactRuntime.run()` 会原地修改传入的 `messages` 列表，`Claw` 只需要在流结束后保存同一个列表即可。

## 10. Hook 生命周期

`hooks.py` 提供内部扩展点。当前默认没有注册自定义 hook，但 Runtime 在关键位置会调用：

| Hook | 触发时机 |
|------|----------|
| `on_run_start` | 一次用户请求开始 |
| `on_user_message` | 用户消息追加后 |
| `before_iteration` | 每轮 ReAct 迭代开始 |
| `before_build_messages` / `after_build_messages` | 构建模型请求消息前后 |
| `before_model_call` | 调用模型前 |
| `after_model_stream` | 模型流式响应结束并累积成 turn 后 |
| `after_assistant_message` | assistant 消息追加到历史后 |
| `before_tool_call` / `after_tool_call` | 工具执行前后 |
| `before_next_iteration` | 工具执行完成，进入下一轮模型调用前 |
| `before_save` | Runtime 准备结束并由上层保存前 |
| `on_run_end` | 一次用户请求正常结束 |
| `on_error` | Runtime 捕获异常后 |

这些 hook 是后续接入上下文压缩、长期记忆、模型路由、工具治理、审计追踪的主要集成点。

## 11. 当前限制

- 会话存储仍是同步 JSON 文件读写，没有并发写保护。
- `execute_command` 使用 `shell=True`，需要额外安全治理后才适合更开放的使用场景。
- 上下文 token 使用量为保守估算，不是具体模型 tokenizer 的精确计数；超长单条消息仍可能超过模型上下文限制。
- Skill frontmatter 解析是轻量正则解析，不是完整 YAML 解析器。
- WebSocket 错误处理较简单，异常时会关闭连接。
