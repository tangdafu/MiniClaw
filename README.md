# MiniClaw Agent

一个支持工具调用的 AI Agent 对话项目。

## 功能

- 与大模型进行流式对话
- 大模型可自动调用工具（如执行命令）
- 前端实时显示工具调用过程和结果
- 支持 Markdown 渲染

## 项目结构

```
MiniClaw/
├── backend/              # FastAPI 后端 (uv 管理)
│   ├── main.py           # API 入口
│   ├── tools.py          # 工具定义（使用 miniclaw 封装）
│   ├── miniclaw/         # 核心 Agent 封装包
│   │   ├── __init__.py
│   │   ├── agent.py      # Agent 类（对话 + 工具调用循环）
│   │   └── types.py      # Tool / Event 类型定义
│   ├── pyproject.toml
│   └── uv.lock
├── frontend/             # Vue 3 前端
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

### 直接使用 miniclaw 封装（不依赖 FastAPI）

```python
from miniclaw import Agent, Tool

# 定义工具
tools = [
    Tool(name="...", description="...", parameters={...}, handler=func),
]

# 创建 Agent
agent = Agent(
    api_key="sk-xxx",
    base_url="https://api.openai.com/v1",
    model="gpt-4o",
    tools=tools,
)

# 流式对话
async for event in agent.chat(messages):
    print(event)
```
