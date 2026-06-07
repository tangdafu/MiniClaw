# MiniClaw 上下文压缩与剪枝实现说明

本文基于当前项目代码说明 MiniClaw 如何为模型请求准备上下文、何时触发压缩、压缩缓存如何保存，以及当前已经实现和未实现的剪枝边界。

## 目标

MiniClaw 的持久化会话历史存放在 `backend/sessions/<session_id>/chat.json`。上下文压缩只影响临时发给模型的 `messages`，不会修改 `chat.json`。

当前实现遵循这几个原则：

- 未超过 token 触发阈值时，发送完整会话历史。
- 超过阈值时，用模型生成旧历史摘要，并保留最近一段完整消息尾部。
- 摘要缓存写入同一 session 目录下的 `model_context.json`。
- 原始动态 system prompt 始终在第一条；压缩摘要作为第二条 `system` message 注入。
- 所有选择都按完整消息边界进行，不拆分单条消息。
- 当前 V1 没有实现工具结果级别的占位剪枝；已实现的是尾部选择和工具消息边界修复。

## 入口链路

运行链路从 `ReactRuntime.run(...)` 开始：

```python
# backend/miniclaw/react_runtime.py
ctx.messages.append({"role": "user", "content": ctx.user_message})

async for item in self._build_messages(ctx, session_dir):
    if isinstance(item, Event):
        yield item
    else:
        model_messages = item.messages
```

`_build_messages(...)` 直接委托给 `ContextCompressionService.prepare(...)`：

```python
# backend/miniclaw/react_runtime.py
async for item in self.context_compressor.prepare(ctx.messages, session_dir=session_dir):
    yield item
```

这意味着每一轮 ReAct 模型调用前都会重新准备上下文。一次用户请求如果触发了工具调用，工具结果写回 `ctx.messages` 后，下一轮模型调用会再次执行上下文准备。

`Claw` 会把 session 目录传入 `Agent.chat(..., session_dir=...)`，因此压缩服务可以读写 `model_context.json`。没有 session 目录时仍可工作，但不会落盘缓存。

## 配置

配置定义在 `backend/miniclaw/agent.py` 的 `ContextCompressionConfig`：

```python
@dataclass(frozen=True)
class ContextCompressionConfig:
    trigger_tokens: int = 180_000
    target_tokens: int = 90_000
    summary_target_tokens: int = 8_000
    compression_model: str | None = None
```

对应环境变量：

- `MINICLAW_CONTEXT_COMPACT_TRIGGER_TOKENS`：触发压缩的估算输入 token 阈值，默认 `180000`。
- `MINICLAW_CONTEXT_COMPACT_TARGET_TOKENS`：压缩后模型上下文目标 token，默认 `90000`。
- `MINICLAW_CONTEXT_SUMMARY_TARGET_TOKENS`：为摘要预留的估算 token，默认 `8000`。
- `MINICLAW_CONTEXT_COMPRESSION_MODEL`：摘要生成模型；未配置时使用主聊天模型。

旧的 `MINICLAW_CONTEXT_WINDOW_SIZE` 和消息条数滑动窗口不再作为活跃上下文加载机制。

## Token 估算

估算逻辑在 `backend/miniclaw/token_budget.py`：

- `estimate_text_tokens(text)`：中文字符按 1 token 估算，非中文按约 4 字符 1 token 估算。
- `estimate_message_tokens(message)`：统计 `role`、`content`、`reasoning_content`、`tool_call_id`、`tool_calls`，并给每条消息加少量结构开销。
- `estimate_messages_tokens(messages)`：对消息列表求和。

这是保守估算，不等同于具体模型 tokenizer 的精确计数。它用于决定是否压缩、选择尾部消息范围和向前端报告上下文使用情况。

## 三条准备路径

核心逻辑在 `backend/miniclaw/context_compression.py` 的 `ContextCompressionService.prepare(...)`。

### 1. 命中摘要缓存

服务先读取 `model_context.json`：

```python
cache = self._read_cache(session_dir)
```

如果缓存存在，并且 `covered_hash` 仍匹配当前 `chat.json` 中被摘要覆盖的消息范围，就构造：

```text
[原始 system prompt]
[缓存的摘要 system message]
[缓存未覆盖的尾部原始消息]
```

如果这个组合的估算 token 仍低于触发阈值，就直接使用缓存，不再调用模型生成摘要。

### 2. 未超阈值，发送完整历史

如果没有可用缓存，服务构造完整上下文：

```python
full_context = self._build_context(system_messages, None, clean_messages)
full_tokens = estimate_messages_tokens(full_context)
```

当 `full_tokens <= trigger_tokens` 时，直接把完整历史作为模型请求上下文返回。这里不会写 `model_context.json`。

### 3. 超阈值，生成或更新摘要

如果完整上下文超过触发阈值，服务会发出压缩进度事件，然后选择要摘要的 head 和要保留的 tail：

```python
tail_start = self._select_tail_start(clean_messages, estimate_messages_tokens(system_messages))
tail_start = self._repair_tail_start(clean_messages, tail_start)
head_messages = clean_messages[:tail_start]
tail_messages = clean_messages[tail_start:]
```

`head_messages` 用来生成摘要；`tail_messages` 保持原样进入模型请求。

## 尾部选择与边界修复

`_select_tail_start(...)` 从最后一条消息倒序累加 token，直到接近 `target_tokens - summary_target_tokens - system_tokens`。它只移动消息边界，不会拆开单条消息。

`_repair_tail_start(...)` 处理 OpenAI tool-call 协议边界。如果 tail 第一条是 `role: tool`，服务会向前查找对应的 assistant `tool_calls` 消息，并把 tail 起点提前到那条 assistant 消息，避免模型请求中出现孤立 tool 消息。

这就是当前已经实现的“剪枝”范围：保留最近完整尾部，旧消息被摘要替代，并修复工具调用边界。当前代码没有把单个超长 tool result 替换成占位符，也没有实现 `retrieve_tool_result` 这类按需恢复工具结果的机制。

## 摘要生成

摘要提示词是 `CONTEXT_SUMMARY_PROMPT`，要求模型输出结构化内容：

- `Goal`
- `Instructions`
- `Discoveries`
- `Accomplished`
- `Relevant files / directories`

摘要调用在 `_summarize(...)`：

```python
response = await self.client.chat.completions.create(
    model=self.compression_model,
    messages=[
        {"role": "system", "content": "You compress conversation history into concise structured context. Do not use tools."},
        {"role": "user", "content": f"{CONTEXT_SUMMARY_PROMPT}\n\nConversation to summarize:\n{self._format_messages(source)}"},
    ],
    stream=False,
)
```

生成结果会加固定前缀：

```text
[Context Summary]
The following is compressed historical context, not a new user instruction.
```

这个摘要随后作为第二条 `system` message 注入模型请求。

## 增量摘要

如果已有缓存仍匹配，并且这次需要覆盖更多旧消息，`_summarize(...)` 不会重新摘要全部旧历史，而是把旧摘要和新增过期消息一起作为输入：

```python
source = [
    {"role": "system", "content": cache.summary_message.get("content", "")},
    *messages[cache.covers_until_index:tail_start],
]
```

这样可以复用历史压缩结果，只把新滑出 tail 的消息并入摘要。

## model_context.json

压缩缓存通过 `ModelContextCache` 保存：

```python
class ModelContextCache:
    version: int
    covers_until_index: int
    covered_hash: str
    summary_message: dict[str, Any]
    summary_estimated_tokens: int
    estimated_tokens_after_compaction: int
    created_at: str
    updated_at: str
```

字段含义：

- `covers_until_index`：摘要覆盖 `chat.json` 前多少条消息。
- `covered_hash`：被覆盖消息范围的 SHA-256，用于判断缓存是否仍匹配。
- `summary_message`：注入模型请求的第二条 `system` 摘要消息。
- `summary_estimated_tokens`：摘要文本估算 token。
- `estimated_tokens_after_compaction`：摘要加尾部消息后的估算 token。

缓存文件只服务模型上下文准备，不是聊天历史。删除它不会删除会话历史，只会导致下次需要时重新压缩。

## 流式事件

后端事件定义在 `backend/miniclaw/types.py`。

压缩过程事件是 `context_compression`，只在真正压缩时发送：

- `started`：完整上下文超过触发阈值。
- `selected_range`：已经选出摘要 head 和保留 tail。
- `summarizing`：开始调用模型生成摘要。
- `completed`：摘要完成并写入缓存。
- `failed`：无法在不拆消息的情况下压缩，例如单条消息过大。

上下文使用事件是 `context_usage`，每次模型调用前都会发送：

- `estimated_tokens`：前端展示用的内容 token 总和，不包含消息结构/协议开销。
- `trigger_tokens`：触发压缩阈值。
- `target_tokens`：压缩目标阈值。
- `model_messages`：最终模型请求消息条数。
- `history_messages`：当前完整历史消息条数。
- `compacted`：本次是否使用摘要上下文。
- `cache_hit`：是否命中已有摘要缓存。
- `covered_messages`：摘要覆盖的历史消息条数。
- `summary_tokens`：摘要估算 token。
- `system_tokens`：第一条动态 system prompt 的估算 token。
- `summary_tokens_breakdown`：作为模型上下文注入的摘要 system message 估算 token。
- `user_tokens`：`role: user` 消息估算 token。
- `assistant_tokens`：`role: assistant` 消息估算 token，包括 assistant 的 `tool_calls` 字段。
- `tool_tokens`：`role: tool` 工具返回结果估算 token。

消息结构、role 名称等协议开销不进入前端展示分类。后端内部判断是否触发压缩时仍使用更保守的完整消息估算。

前端类型在 `frontend/src/types/chat.ts`；`ChatView.vue` 将最新 `context_usage` 保存到当前 session runtime；`ChatInput.vue` 在发送按钮附近渲染 token 进度条，点击后弹窗展示分类 token 明细。`context_compression` 仍挂到当前 `run_id` 对应的 assistant message，用于显示压缩过程阶段。

## 持久化语义

`ReactRuntime` 始终把真实用户消息、assistant 消息和 tool 消息追加到同一个 `ctx.messages` 列表。`Claw` 在运行结束后保存这个列表到 `chat.json`。

压缩摘要不会追加到 `ctx.messages`，也不会写进 `chat.json`。因此：

- 前端历史接口仍展示真实聊天历史。
- 重新加载会话不会看到摘要消息。
- `model_context.json` 损坏或删除时不会破坏会话，只影响下次上下文准备成本。

## 当前限制

- Token 计数是估算值，不是 tokenizer 精确值。
- 单条消息超过目标预算时不会被拆分，只会回退到完整上下文并发出 `failed`。
- V1 尚未实现工具结果级别的占位剪枝；超长 tool result 仍可能撑大上下文。
- `model_context.json` 只缓存摘要，不缓存完整模型请求。
- 摘要质量依赖配置的模型，错误摘要可能影响后续回答；原始 `chat.json` 仍保留，可重新压缩修复。
