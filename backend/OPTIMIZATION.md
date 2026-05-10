# MiniClaw 后端待优化点文档

> 生成日期：2026-05-11
> 审查范围：`backend/` 全部核心代码
> 重点需求：长期记忆与短期记忆架构设计

---

## 一、严重缺陷（必须修复）

### 1. 【严重】Claw 保存的 assistant 消息缺失 `tool_calls`，导致上下文断裂

**问题描述：**

在 `claw.py` 第 135-145 行，当对话结束时，Claw 只收集了 `text` 和 `reasoning` 内容来构建 assistant 消息：

```python
assistant_msg = {
    "role": "assistant",
    "content": assistant_content
}
if assistant_reasoning:
    assistant_msg["reasoning_content"] = assistant_reasoning
messages.append(assistant_msg)
```

但 Agent 在内部实际发送给 LLM 的 assistant 消息包含了 `tool_calls`（`agent.py` 第 168 行）：

```python
assistant_message["tool_calls"] = parser.get_tool_calls()
current_messages.append(assistant_message)
```

同时 Agent 还追加了 `role: "tool"` 的消息（`agent.py` 第 181-185 行）。

**后果：**
- Claw 持久化的 `chat.json` 中，assistant 消息**没有** `tool_calls` 字段
- Claw 持久化的 `chat.json` 中**没有** `role: "tool"` 的消息
- 下一轮对话加载历史时，LLM 看到 assistant 说"我要执行命令"，但**看不到**它实际调用了什么工具、也**看不到**工具返回的结果
- LLM 会困惑、重复调用工具、或产生幻觉

**修复方向：**
- 方案 A：Agent 将完整的消息历史（包含 tool_calls 和 tool 消息）返回给 Claw，Claw 统一持久化
- 方案 B：Claw 不再自己组装消息，而是监听 Event 流重构完整消息历史
- 推荐方案 A，在 Agent.chat() 结束后返回最终 messages 列表

---

### 2. 【严重】没有上下文窗口管理，长对话必然崩溃

**问题描述：**

当前 `Agent.chat()` 直接将完整历史发送给 LLM（`agent.py` 第 137 行）：

```python
response = await self.client.chat.completions.create(
    model=self.model,
    messages=current_messages,  # 完整历史，无限增长
    ...
)
```

没有任何 token 计数、消息截断、或滑动窗口机制。

**后果：**
- 随着对话轮次增加，`current_messages` 越来越长
- 最终会超出模型的 `max_context_length`，导致 API 返回 400 错误
- 没有优雅降级策略，直接报错终止对话

**修复方向：**
- 引入 `TokenCounter` 或基于字符数的估算器
- 实现消息截断策略（如保留最近 N 轮，或保留系统提示 + 最近消息）
- 与长期记忆系统联动：旧消息摘要化后存入长期记忆，短期记忆只保留最近窗口

---

### 3. 【严重】`reasoning_content` 字段可能导致 OpenAI API 调用失败

**问题描述：**

`agent.py` 第 143 行初始化 assistant 消息时：

```python
assistant_message: dict = {"role": "assistant", "content": "", "reasoning_content": ""}
```

`types.py` 第 22-23 行的 `to_openai_dict()` 也会将 `reasoning_content` 序列化到 API 请求中。

**后果：**
- `reasoning_content` 是 DeepSeek 等国产模型的专有字段，**OpenAI 官方 API 不支持**
- 如果用户使用 OpenAI 官方 API，请求中携带未知字段可能导致 API 报错或忽略
- 即使某些 API 兼容该字段，也不应该在 assistant 消息中主动发送空字符串 `""`

**修复方向：**
- 仅在检测到模型支持 reasoning 时才保留该字段（如 DeepSeek-R1）
- 或者将 reasoning_content 从发送给 API 的消息中剥离，仅用于内部展示和持久化
- 修改 `Message.to_openai_dict()`，默认不输出 `reasoning_content`

---

### 4. 【严重】`SessionManager` 使用同步 IO 阻塞异步事件循环

**问题描述：**

`SessionManager` 的所有方法都是同步的：

```python
# claw.py 第 32, 49, 60, 67 行
chat_file.write_text("[]", encoding="utf-8")      # 同步写
chat_file.read_text(encoding="utf-8")              # 同步读
json.dumps(...)                                    # 大数据量时阻塞
```

虽然单次读写很快，但在高并发或会话数据很大时，会阻塞整个 asyncio 事件循环。

**后果：**
- 并发请求时性能下降
- 大 JSON 文件解析时造成明显的请求延迟
- 不符合 FastAPI 异步最佳实践

**修复方向：**
- 使用 `aiofiles` 进行异步文件读写
- 大数据量操作使用 `asyncio.to_thread()`  offload 到线程池
- 或者引入异步数据库（如 SQLite + aiosqlite）替代文件系统

---

## 二、架构设计缺陷

### 5. 【架构】缺乏长期记忆与短期记忆的显式分层

**当前状态：**

当前只有一个"会话历史"，所有消息原样保存、原样发送给 LLM。没有长期记忆和短期记忆的区分。

**问题：**
- **没有短期记忆管理**：没有滑动窗口、没有 token 预算、没有消息重要性评估
- **没有长期记忆**：没有对话摘要、没有向量嵌入检索、没有跨会话记忆
- **没有记忆压缩**：对话越长，上下文越臃肿，成本越高、延迟越大

**期望架构：**

```
用户输入
    │
    ▼
┌─────────────────────────────────────────┐
│  短期记忆 (Short-term Memory)            │
│  • 最近 N 轮完整对话（保留细节）         │
│  • Token 预算管理（如 4k/8k 窗口）       │
│  • 超出窗口的旧消息 → 触发摘要           │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│  长期记忆 (Long-term Memory)             │
│  • 对话摘要（按主题/时间段聚合）         │
│  • 向量存储（关键信息嵌入检索）          │
│  • 用户偏好、事实库（显式存储）          │
└─────────────────────────────────────────┘
    │
    ▼
  构建最终 messages → 发送给 LLM
```

**修复方向：**
- 引入 `Memory` 抽象层，分为 `ShortTermMemory` 和 `LongTermMemory`
- `ShortTermMemory`：管理滑动窗口，维护最近 N 轮对话，支持 token 预算
- `LongTermMemory`：
  - 定期对旧对话生成摘要
  - 关键信息提取（如用户偏好、重要事实）
  - 向量检索（需要时从长期记忆中召回相关内容）
- 系统提示中注入长期记忆摘要，让 LLM 了解背景

---

### 6. 【架构】Claw 与 Agent 消息历史双轨维护，职责边界模糊

**问题描述：**

- `Agent.chat(messages)` 接收 messages，内部构建 `current_messages`（包含 system_prompt、tool_calls、tool 结果）
- `Claw.chat()` 也维护一个 `messages` 列表，只保存 user 和 assistant（不含 tool_calls）
- 两者**不共享状态**，Agent 内部的完整历史对 Claw 不可见

**后果：**
- 数据冗余且不一致
- Claw 无法获取 Agent 内部的 tool 调用详情来持久化
- 如果未来需要在 Claw 层做消息拦截/修改（如记忆注入），无法操作 Agent 内部的 current_messages

**修复方向：**
- 明确分层：
  - **Agent**：只负责"一轮"LLM 调用（输入 messages → 输出 Event 流 + 最终消息列表）
  - **Claw**：负责会话生命周期、记忆管理、消息持久化。调用 Agent 后，将 Agent 返回的完整消息列表保存
- Agent.chat() 的返回值应包含完整的对话历史，Claw 负责持久化

---

### 7. 【架构】`Event` 类型混合了不同层的事件

**问题描述：**

`Event` 类型定义在 `types.py` 中，但包含了：
- Agent 层事件：`text`, `reasoning`, `tool_call`, `tool_result`, `done`, `error`
- Claw 层控制事件：`session_created`

**后果：**
- 职责不清，Claw 的控制逻辑泄漏到核心类型中
- 如果未来增加更多编排层事件（如 `memory_recall`, `session_loaded`），Event 会越来越臃肿

**修复方向：**
- 将 `Event` 拆分为：
  - `AgentEvent`（核心层）：text, reasoning, tool_call, tool_result, done, error
  - `ClawEvent`（编排层）：继承/包装 AgentEvent，增加 session_created, memory_recall 等
- 或者使用更灵活的事件结构（如 dict + schema 验证）

---

### 8. 【架构】`SessionManager` 设计过于简单，无法支撑生产需求

**问题描述：**

当前 `SessionManager` 只是简单的 JSON 文件读写：
- 没有并发控制（多个请求同时写同一个文件会冲突）
- 没有事务性（写一半崩溃会损坏文件）
- 没有索引（无法按时间、按内容搜索会话）
- 全量读写：append 一条消息也要加载整个 JSON、修改、再写回

**修复方向：**
- 短期：使用文件锁（`filelock`）保证并发安全；使用 aiofiles 异步化
- 中期：迁移到 SQLite，每条消息一行，支持分页查询
- 长期：考虑 PostgreSQL / MongoDB 等数据库，支持全文搜索和向量检索

---

## 三、代码实现问题

### 9. 【代码】`execute_command` 安全风险

**问题描述：**

```python
# tools.py 第 130 行
result = subprocess.run(command, shell=True, ...)
```

- 使用 `shell=True`，且没有命令白名单/黑名单
- 任何通过 LLM 生成的命令都会直接执行
- LLM 可能被诱导执行 `rm -rf /`、`curl ... | bash` 等危险命令

**修复方向：**
- 添加命令白名单/黑名单机制
- 或者使用更安全的方式（如 `shlex.split()` + `shell=False`）
- 添加确认机制：危险命令需要用户确认
- 限制可访问的目录范围（chroot/sandbox）

---

### 10. 【代码】`SkillManager` 没有缓存，重复解析文件

**问题描述：**

每次调用 `read_skill_list()` 都会遍历目录、读取并解析所有 `SKILL.md`：

```python
# tools.py 第 21-39 行
for item in self.skills_dir.iterdir():
    ...
    meta = self._parse_frontmatter(skill_md)  # 每次都读文件
```

**后果：**
- LLM 每次调用 `read_skill_list` 都触发磁盘 IO
- 如果 Skill 很多，性能下降明显

**修复方向：**
- 添加内存缓存（如 `functools.lru_cache` 或自定义缓存）
- 监听文件修改时间，缓存失效时重新加载
- 或者在启动时预加载所有 Skill 元数据

---

### 11. 【代码】`SkillManager._parse_frontmatter` 解析过于简陋

**问题描述：**

```python
# tools.py 第 106-123 行
for line in frontmatter.strip().split('\n'):
    if ':' in line:
        key, value = line.split(':', 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
```

- 不支持多行值、不支持嵌套结构、不支持列表
- 如果 frontmatter 中有冒号（如 URL `https://...`），会错误分割
- 不支持 YAML 标准格式（如 `name: "my skill"` 中的引号处理不完整）

**修复方向：**
- 使用 `PyYAML` 或 `yaml` 标准库解析 frontmatter
- 或者至少使用更健壮的解析逻辑

---

### 12. 【代码】`read_skill` 路径安全检查写法绕

**问题描述：**

```python
# tools.py 第 70-73 行
try:
    target_file.resolve().relative_to(item.resolve())
except ValueError:
    return "[错误] 文件路径不合法"
```

- 使用 `relative_to()` 的异常来判断路径是否在目录内，逻辑绕
- Python 3.9+ 有 `Path.is_relative_to()` 方法，更清晰

**修复方向：**
- 使用 `if not target_file.resolve().is_relative_to(item.resolve()):`

---

### 13. 【代码】WebSocket 错误处理过于粗暴

**问题描述：**

```python
# main.py 第 104-107 行
except Exception as e:
    logger.exception("WebSocket error")
    await websocket.send_json({"type": "error", "error": str(e)})
    await websocket.close()
```

- 任何异常都直接关闭连接，没有重试或恢复机制
- 如果只是一个消息处理失败，整个 WebSocket 连接就断了
- 没有区分可恢复错误（如消息格式错误）和致命错误

**修复方向：**
- 只关闭连接在致命错误时（如连接断开）
- 消息处理错误时返回 error event，但保持连接继续接收下一条消息
- 添加心跳机制检测连接状态

---

### 14. 【代码】Agent 达到最大迭代次数时消息丢失

**问题描述：**

```python
# agent.py 第 187-188 行
yield Event.text("\n\n[达到最大迭代次数，对话结束]")
yield Event.done()
```

- 达到 `max_iterations` 后，Agent 直接 yield done 并退出
- 但此时最后一轮的 assistant 消息（可能包含重要的 tool_calls）**没有**被添加到 `current_messages`
- Claw 在收到 done 后保存 messages，但这条 assistant 消息缺失

**修复方向：**
- 在达到 max_iterations 前，将最后一轮的 assistant_message 和 tool 结果追加到历史
- 或者将 max_iterations 的处理权交给 Claw，Agent 只负责单轮调用

---

### 15. 【代码】`Agent._build_messages` 可能重复插入 system_prompt

**问题描述：**

```python
# agent.py 第 89-95 行
def _build_messages(self, messages: list[dict]) -> list[dict]:
    result = []
    if self.system_prompt:
        result.append({"role": "system", "content": self.system_prompt})
    result.extend(messages)
    return result
```

- 如果 `messages` 中已经包含 system 消息（比如从持久化加载的），会重复插入
- 某些 API 对多个 system 消息支持不一致

**修复方向：**
- 检查 messages 中是否已有 system 角色，避免重复
- 或者将 system_prompt 的管理完全交给 Claw/上层，Agent 只负责透传

---

### 16. 【代码】`Claw.chat` 对无效 session_id 的处理不友好

**问题描述：**

```python
# claw.py 第 109 行
if not session_id or not self.session_manager.session_exists(session_id):
    session_id = self.create_session()
    yield Event.session_created(session_id)
```

- 如果用户传了一个**不存在**的 session_id（比如过期或被删除），静默创建新会话
- 用户可能以为在继续旧会话，但实际上是新会话，造成困惑

**修复方向：**
- 区分"空 session_id"（创建新会话，正常）和"无效 session_id"（返回错误提示）

---

### 17. 【代码】`Tool.handler` 类型签名过于宽松

**问题描述：**

```python
# types.py 第 32 行
handler: Callable[..., Any]  # 同步或异步函数
```

- `Callable[..., Any]` 过于宽松，没有参数和返回值的约束
- 无法静态检查工具函数签名是否与 `parameters` JSON Schema 匹配

**修复方向：**
- 考虑使用 `Protocol` 或泛型来增强类型安全
- 或者至少在运行时检查 handler 的签名与 parameters 是否兼容

---

## 四、优化建议汇总（按优先级排序）

| 优先级 | 问题 | 影响 | 建议修复方案 |
|--------|------|------|-------------|
| **P0** | Claw 保存的 assistant 消息缺失 tool_calls | 上下文断裂，LLM 幻觉 | Agent 返回完整消息列表给 Claw 持久化 |
| **P0** | 没有上下文窗口管理 | 长对话必然崩溃 | 引入 TokenCounter + 消息截断策略 |
| **P0** | reasoning_content 兼容性问题 | OpenAI API 可能报错 | 发送给 API 前剥离 reasoning_content |
| **P0** | SessionManager 同步 IO | 阻塞事件循环 | 使用 aiofiles 或 asyncio.to_thread |
| **P1** | 缺乏长期/短期记忆分层 | 无法支撑复杂对话 | 设计 Memory 抽象层，实现摘要+向量检索 |
| **P1** | Claw 与 Agent 双轨维护消息 | 数据不一致 | 明确分层，Agent 返回完整历史 |
| **P1** | Event 类型混合 | 职责不清 | 拆分为 AgentEvent / ClawEvent |
| **P1** | execute_command 安全风险 | 可执行任意命令 | 添加命令白名单/确认机制 |
| **P2** | SessionManager 无并发控制 | 数据损坏风险 | 文件锁或迁移到数据库 |
| **P2** | SkillManager 无缓存 | 重复磁盘 IO | 启动时预加载 + 内存缓存 |
| **P2** | frontmatter 解析简陋 | 解析错误 | 使用 PyYAML 标准解析 |
| **P2** | WebSocket 错误处理粗暴 | 用户体验差 | 区分可恢复/致命错误 |
| **P2** | max_iterations 消息丢失 | 上下文丢失 | 保存最终轮消息后再退出 |
| **P3** | system_prompt 可能重复 | API 兼容问题 | 检查 messages 中是否已有 system |
| **P3** | 无效 session_id 静默创建 | 用户困惑 | 区分空 ID 和无效 ID 的处理 |
| **P3** | Tool.handler 类型宽松 | 缺少静态检查 | 使用 Protocol 增强类型安全 |

---

## 五、长期记忆与短期记忆架构设计建议

基于你的需求，建议引入以下架构：

### 5.1 核心抽象

```python
# 建议新增模块：miniclaw/memory.py

class Memory(ABC):
    """记忆抽象基类"""
    @abstractmethod
    async def add(self, message: Message) -> None: ...
    @abstractmethod
    async def get_context(self, query: str | None = None) -> list[dict]: ...

class ShortTermMemory(Memory):
    """短期记忆：滑动窗口，保留最近 N 轮完整对话"""
    def __init__(self, max_tokens: int = 4000, max_messages: int = 20):
        self.max_tokens = max_tokens
        self.max_messages = max_messages
        self.messages: list[Message] = []

    async def add(self, message: Message) -> None:
        self.messages.append(message)
        await self._compress_if_needed()

    async def _compress_if_needed(self) -> None:
        # 超出 token 预算时，将旧消息摘要后存入长期记忆
        # 保留最近 max_messages 条
        ...

class LongTermMemory(Memory):
    """长期记忆：摘要 + 向量检索"""
    def __init__(self, vector_store, summary_model):
        self.summaries: list[str] = []  # 对话摘要列表
        self.facts: dict[str, str] = {}  # 关键事实（用户偏好等）
        self.vector_store = vector_store  # 向量存储（如 faiss/chroma）

    async def add(self, message: Message) -> None:
        # 提取关键信息、更新摘要、存入向量库
        ...

    async def get_context(self, query: str | None = None) -> list[dict]:
        # 返回相关摘要和事实，作为 system prompt 注入
        ...
```

### 5.2 与现有架构的集成点

```
Claw.chat(session_id, user_message)
    │
    ▼
加载历史 ──→ SessionManager.load_messages()
    │
    ▼
构建记忆上下文 ──→ MemoryManager
    │   ├─ ShortTermMemory.get_context() → 最近 N 轮完整对话
    │   └─ LongTermMemory.get_context(query=user_message) → 相关摘要/事实
    │
    ▼
组装 messages ──→ [system(长期记忆摘要)] + [短期记忆窗口] + [user_message]
    │
    ▼
调用 Agent.chat(messages)
    │
    ▼
保存结果 ──→ SessionManager.save_messages() + MemoryManager.add()
```

### 5.3 关键设计决策

1. **何时触发长期记忆写入？**
   - 方案 A：每轮对话后，短期记忆溢出时触发摘要
   - 方案 B：会话结束时统一摘要
   - 推荐方案 A，更实时

2. **摘要由谁生成？**
   - 使用轻量级模型或同模型快速生成
   - 摘要内容：对话主题、关键结论、用户意图

3. **向量检索的粒度？**
   - 按"轮次"嵌入：每轮对话生成一个向量
   - 按"主题"嵌入：提取关键句子单独嵌入
   - 推荐混合策略

4. **用户偏好/事实如何提取？**
   - 使用结构化提取（如让 LLM 输出 JSON：{"preference": ..., "fact": ...}）
   - 显式存储在 `LongTermMemory.facts` 中
   - 每次对话前注入 system prompt

---

## 六、下一步行动建议

1. **立即修复 P0 问题**（1-2 天）：
   - 修复 tool_calls 丢失问题
   - 修复 reasoning_content 兼容性问题
   - 异步化 SessionManager

2. **设计 Memory 架构**（3-5 天）：
   - 定义 Memory 抽象接口
   - 实现 ShortTermMemory（滑动窗口）
   - 实现基础的 LongTermMemory（摘要 + 简单关键词检索）

3. **增强长期记忆**（1-2 周）：
   - 引入向量数据库（如 ChromaDB 或 SQLite-vec）
   - 实现自动摘要生成
   - 实现用户偏好提取

4. **安全与性能优化**（持续）：
   - 命令执行安全加固
   - Skill 缓存机制
   - 会话存储迁移到数据库
