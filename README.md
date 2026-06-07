# MiniClaw Agent

一个支持工具调用的 AI Agent 对话项目，采用分层架构设计，支持流式对话、会话持久化、Skill 管理和工具调用。

## 功能

- 与大模型进行流式对话（WebSocket）
- 大模型可自动调用工具（如执行命令、读取 Skill 等）
- 前端实时显示工具调用过程和结果
- 支持 Markdown 渲染
- 支持多会话管理与持久化
- 支持 Skill 动态加载与管理

## 后端架构

后端采用“入口层 → 会话编排层 → Agent 门面 → ReAct Runtime → 工具层”的分层设计。`Agent` 对外保持稳定接口，真正的多轮 ReAct 运行逻辑已经拆到 `ReactRuntime` 及其配套组件中。

```
┌─────────────────────────────────────────────────────────────┐
│                      入口层 (main.py)                        │
│  FastAPI + WebSocket 接口 / 生命周期管理 / 依赖注入           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   编排层 (miniclaw/claw.py)                  │
│  Claw — 上下文管理与 Agent 编排                              │
│  • 会话生命周期管理（创建、读取、保存）                      │
│  • 消息历史拼接与持久化                                     │
│  • 调用 Agent 并流式返回 Event                              │
│  SessionManager — 基于文件系统的会话持久化                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Agent 门面层 (miniclaw/agent.py)            │
│  Agent — 稳定对外接口                                       │
│  • 读取 AgentConfig                                         │
│  • 初始化 OpenAI 兼容客户端                                 │
│  • 保持 Agent.chat(messages, user_message) 接口不变          │
│  • 委托 ReactRuntime 执行真正的 ReAct 循环                   │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│               Runtime 层 (miniclaw/react_runtime.py)         │
│  ReactRuntime — ReAct 编排循环                               │
│  • 构建模型请求消息                                          │
│  • 调用 OpenAI 兼容流式 API                                  │
│  • 通过 StreamAccumulator 累积 text/reasoning/tool_calls     │
│  • 通过 ToolExecutor 执行工具                                │
│  • 原地更新 messages，并输出 Event 流                        │
│  • 通过 HookManager 暴露内部生命周期扩展点                   │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                  工具层 (tools.py + miniclaw/tools/)         │
│  • tools.py — 兼容入口，暴露 get_tools()                     │
│  • registry.py — 组合内置工具                               │
│  • skills.py — SkillRepository + Skill 读取工具              │
│  • command.py — CommandRunner + 命令执行工具                 │
│  • files.py — 文件读取/列表/搜索/写入/替换工具               │
└─────────────────────────────────────────────────────────────┘
```

### 核心模块说明

| 模块 | 职责 |
|------|------|
| `main.py` | FastAPI 应用入口，提供 WebSocket `/ws/chat` 和 `/health` 接口，管理应用生命周期 |
| `miniclaw/claw.py` | **编排层**。`Claw` 负责会话上下文管理、`Agent` 调用编排；`SessionManager` 负责会话的持久化读写 |
| `miniclaw/agent.py` | **Agent 门面层**。`Agent` 保持 `chat(messages, user_message)` 对外接口，并委托 `ReactRuntime` 执行；`AgentConfig` 管理配置 |
| `miniclaw/react_runtime.py` | **Runtime 核心层**。执行多轮 ReAct 循环，负责模型调用、事件输出、工具调用协调、消息历史更新和 hook 调度 |
| `miniclaw/react_context.py` | Runtime 数据结构：`ReactContext`、`ModelRequest`、`ModelTurn`、`ToolExecution` |
| `miniclaw/stream.py` | 流式增量累积。重建 assistant 文本、reasoning 内容和 OpenAI 风格的 `tool_calls` |
| `miniclaw/tool_executor.py` | 工具执行器。负责工具查找、JSON 参数解析、同步/异步 handler 调用和错误字符串转换 |
| `miniclaw/hooks.py` | Runtime hook 生命周期定义，提供内部扩展点 |
| `miniclaw/types.py` | 核心类型定义：`Message`（对话消息）、`Tool`（工具定义）、`Event`（流式事件） |
| `tools.py` | **工具兼容入口**。保留 `get_tools()`，委托 `miniclaw.tools` 内部模块组合内置工具 |
| `miniclaw/tools/registry.py` | 内置工具注册模块，返回平铺的 `list[Tool]` |
| `miniclaw/tools/skills.py` | Skill 工具模块，包含 `SkillRepository`、Skill 列表、文件读取和文件树输出 |
| `miniclaw/tools/command.py` | 命令工具模块，包含 `CommandRunner` 和命令工具注册 |
| `miniclaw/tools/files.py` | 通用文件工具模块，包含文件读取、列表/glob、文本搜索、写入和精确替换 |

### 数据流

1. 用户通过 WebSocket 发送 `{ session_id, message }`
2. `main.py` 的 `/ws/chat` 将请求交给 `Claw.chat(session_id, message)`
3. `Claw` 检查或创建会话，加载 `backend/sessions/<session_id>/chat.json` 中的历史消息
4. `Claw` 调用 `Agent.chat(messages, user_message)`，传入可原地修改的完整消息列表
5. `Agent` 委托 `ReactRuntime.run()` 执行多轮 ReAct 循环
6. `ReactRuntime` 追加用户消息、构建模型请求、流式读取模型响应，并通过 `Event` 输出 `text` / `reasoning`
7. 如果模型返回工具调用，`StreamAccumulator` 重建 `tool_calls`，`ToolExecutor` 执行对应工具，并输出 `tool_call` / `tool_result` 事件
8. `ReactRuntime` 将 assistant 消息和 tool 消息追加回同一个 `messages` 列表；包含工具调用时，assistant 消息会保留 OpenAI 兼容的 `tool_calls` 字段
9. 模型不再请求工具时，Runtime 输出 `done`；`Claw` 保存完整消息历史到会话文件
10. 所有事件通过 WebSocket 返回前端，前端实时渲染文本、思考过程、工具调用和工具结果

## 项目结构

```
MiniClaw/
├── backend/                    # FastAPI 后端 (uv 管理)
│   ├── main.py                 # API 入口 (WebSocket + 生命周期)
│   ├── tools.py                # 工具兼容入口（委托 miniclaw.tools）
│   ├── miniclaw/               # 核心 Agent 封装包
│   │   ├── __init__.py         # 包导出
│   │   ├── claw.py             # Claw 编排层 + SessionManager
│   │   ├── agent.py            # Agent 门面 + AgentConfig
│   │   ├── react_runtime.py    # ReAct Runtime 主循环
│   │   ├── react_context.py    # Runtime 上下文与结果数据结构
│   │   ├── stream.py           # 流式响应累积与 tool_calls 重建
│   │   ├── tool_executor.py    # 工具查找、参数解析和执行
│   │   ├── tools/              # 内置工具模块
│   │   │   ├── registry.py     # 组合 Skill 工具和命令工具
│   │   │   ├── skills.py       # SkillRepository 与 Skill 工具
│   │   │   ├── command.py      # CommandRunner 与命令工具
│   │   │   └── files.py        # 通用文件工具
│   │   ├── hooks.py            # Runtime hook 生命周期
│   │   └── types.py            # Tool / Event / Message 类型定义
│   ├── skills/                 # Skill 目录（动态加载）
│   │   └── <skill-name>/
│   │       ├── SKILL.md        # Skill 元数据与指令
│   │       └── ...             # 其他引用文件
│   ├── sessions/               # 会话持久化存储（JSON）
│   ├── .env / .env.example     # 环境变量配置
│   ├── pyproject.toml          # 项目依赖配置
│   └── uv.lock                 # 依赖锁定文件
├── frontend/                   # Vue 3 前端
│   ├── src/
│   │   ├── App.vue
│   │   └── components/ChatView.vue
│   └── package.json
└── README.md
```

## 快速开始

### 1. 配置环境变量

```bash
cd backend
cp .env.example .env
# 编辑 .env，填入你的 API Key 和 Base URL
```

### 2. 启动后端（使用 uv）

```bash
cd backend

# 首次运行：安装依赖
uv sync

# 启动服务
uv run python main.py
```

后端将运行在 http://localhost:8000

> **注意**：如果 `uv sync` 因网络问题超时，可配置国内镜像：
> ```bash
> uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e .
> uv lock
> ```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端将运行在 http://localhost:5173

## 使用

打开浏览器访问 http://localhost:5173，即可开始与 Agent 对话。

当 Agent 需要执行命令时，它会自动调用 `execute_command` 工具，并在界面上显示调用过程和结果。

## 添加新工具

内置工具已经拆分到 `backend/miniclaw/tools/`。新增内置工具时，优先新建或扩展对应领域模块，再在 `registry.py` 中组合；`backend/tools.py` 只作为兼容入口保留。

推荐结构：

```
backend/miniclaw/tools/
├── registry.py      # 组合所有内置工具
├── skills.py        # Skill 相关工具
├── command.py       # 命令执行工具
├── files.py         # 通用文件工具
└── <domain>.py      # 新领域工具
```

当前默认内置的通用文件工具包括：`read_file`、`list_files`、`search_text`、`write_file`、`replace_text`。这些工具先提供基础本地操作能力；安全确认、权限分级和沙箱治理暂不在本阶段实现。

新增工具示例：

```python
from ..types import Tool

async def my_tool(name: str) -> str:
    """工具实现函数"""
    return f"Hello, {name}!"

def get_my_tools() -> list[Tool]:
    return [
        Tool(
            name="my_tool",
            description="这是一个示例工具",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "名字"}
                },
                "required": ["name"]
            },
            handler=my_tool,
        ),
    ]
```

然后在 `backend/miniclaw/tools/registry.py` 中把 `get_my_tools()` 的结果并入 `get_builtin_tools()`。如果只是外部调用方需要拿到当前内置工具，仍然从 `backend/tools.py` 导入 `get_tools()`。

## 添加新 Skill

在 `backend/skills/` 目录下创建新的子目录，并添加 `SKILL.md`：

```
backend/skills/
└── my-skill/
    └── SKILL.md
```

`SKILL.md` 需要包含 YAML frontmatter：

```markdown
---
name: my_skill
description: 这是一个示例 Skill 的简介
---

# 使用说明

这里是 Skill 的详细指令...
```

Agent 可通过 `read_skill_list` 和 `read_skill` 工具动态发现和读取 Skill。

## 直接使用 miniclaw 封装（不依赖 FastAPI）

```python
from miniclaw import Agent, Tool, AgentConfig

# 定义工具
tools = [
    Tool(name="...", description="...", parameters={...}, handler=func),
]

# 创建 Agent
config = AgentConfig(
    api_key="sk-xxx",
    base_url="https://api.openai.com/v1",
    model="gpt-4o",
)
agent = Agent(config=config, tools=tools)

# 流式对话
messages = []
async for event in agent.chat(messages, "你好"):
    print(event)
```

## 环境变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `OPENAI_API_KEY` | OpenAI 兼容 API 的密钥 | - |
| `OPENAI_BASE_URL` | API 基础 URL | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 使用的模型 | `gpt-4o` |
| `MINICLAW_CONTEXT_COMPACT_TRIGGER_TOKENS` | 估算输入 token 超过该值时触发上下文压缩 | `180000` |
| `MINICLAW_CONTEXT_COMPACT_TARGET_TOKENS` | 压缩后模型上下文的目标估算 token | `90000` |
| `MINICLAW_CONTEXT_SUMMARY_TARGET_TOKENS` | 为摘要预留的估算 token | `8000` |
| `MINICLAW_CONTEXT_COMPRESSION_MODEL` | 可选摘要压缩模型；为空时使用聊天模型 | - |

## 技术栈

- **后端**: Python 3.10+, FastAPI, WebSocket, OpenAI SDK, Pydantic, uv
- **前端**: Vue 3, Vite
- **会话存储**: 文件系统 JSON
- **包管理**: uv (Python), npm (Node.js)
