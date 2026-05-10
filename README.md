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

后端采用三层架构设计：

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
│                   核心层 (miniclaw/agent.py)                 │
│  Agent — 纯 Agent Loop                                      │
│  • LLM 流式调用（OpenAI 兼容 API）                          │
│  • 工具调用增量解析                                         │
│  • 自动工具执行循环                                         │
│  • 输出 Event 流（text / reasoning / tool_call / ...）      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     工具层 (tools.py)                        │
│  • execute_command — 本地终端命令执行                       │
│  • SkillManager — Skill 目录解析与管理                      │
│    - read_skill_list / read_skill / list_skill_files        │
└─────────────────────────────────────────────────────────────┘
```

### 核心模块说明

| 模块 | 职责 |
|------|------|
| `main.py` | FastAPI 应用入口，提供 WebSocket `/ws/chat` 和 `/health` 接口，管理应用生命周期 |
| `miniclaw/claw.py` | **编排层**。`Claw` 负责会话上下文管理、`Agent` 调用编排；`SessionManager` 负责会话的持久化读写 |
| `miniclaw/agent.py` | **核心层**。`Agent` 实现纯 LLM 对话循环，自动处理工具调用；`ToolCallParser` 增量解析流式工具调用；`AgentConfig` 管理配置 |
| `miniclaw/types.py` | 核心类型定义：`Message`（对话消息）、`Tool`（工具定义）、`Event`（流式事件） |
| `tools.py` | **工具层**。定义所有可用工具，包括 `SkillManager`（Skill 目录管理）和 `execute_command`（命令执行） |

### 数据流

1. 用户通过 WebSocket 发送 `{ session_id, message }`
2. `Claw` 检查/创建会话，加载历史消息，追加用户消息
3. `Claw` 调用 `Agent.chat(messages)`，传入完整对话历史
4. `Agent` 与 LLM 进行流式对话，自动检测并执行工具调用
5. `Agent` 生成 `Event` 流返回给 `Claw`
6. `Claw` 在对话结束时保存 assistant 回复到会话文件
7. 最终 `Event` 流通过 WebSocket 返回给前端

## 项目结构

```
MiniClaw/
├── backend/                    # FastAPI 后端 (uv 管理)
│   ├── main.py                 # API 入口 (WebSocket + 生命周期)
│   ├── tools.py                # 工具定义（SkillManager + execute_command）
│   ├── miniclaw/               # 核心 Agent 封装包
│   │   ├── __init__.py         # 包导出
│   │   ├── claw.py             # Claw 编排层 + SessionManager
│   │   ├── agent.py            # Agent 类（对话 + 工具调用循环）
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

在 `backend/tools.py` 中使用 `miniclaw.Tool` 封装：

```python
from miniclaw import Tool

async def my_tool(name: str) -> str:
    """工具实现函数"""
    return f"Hello, {name}!"

def get_tools() -> list[Tool]:
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
async for event in agent.chat(messages):
    print(event)
```

## 环境变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `OPENAI_API_KEY` | OpenAI 兼容 API 的密钥 | - |
| `OPENAI_BASE_URL` | API 基础 URL | `https://api.openai.com/v1` |
| `OPENAI_MODEL` | 使用的模型 | `gpt-4o` |

## 技术栈

- **后端**: Python 3.10+, FastAPI, WebSocket, OpenAI SDK, Pydantic, uv
- **前端**: Vue 3, Vite
- **会话存储**: 文件系统 JSON
- **包管理**: uv (Python), npm (Node.js)
