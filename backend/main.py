import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends
from fastapi.middleware.cors import CORSMiddleware

# 显式加载 .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

from miniclaw import Agent, Tool
from miniclaw.agent import AgentConfig
from tools import get_tools

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Agent 单例（由 lifespan 管理生命周期）
_agent: Agent | None = None


def get_agent() -> Agent:
    """获取 Agent 实例（FastAPI 依赖）"""
    if _agent is None:
        raise RuntimeError("Agent not initialized")
    return _agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _agent

    logger.info("Initializing Agent...")
    config = AgentConfig(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
    )
    _agent = Agent(config=config, tools=get_tools())
    logger.info("Agent initialized with %d tools", len(_agent.tools))

    yield

    logger.info("Shutting down...")
    _agent = None


app = FastAPI(
    title="MiniClaw Agent",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    agent: Agent = Depends(get_agent),
):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            messages = data.get("messages", [])

            async for event in agent.chat(messages):
                await websocket.send_json(event.model_dump(exclude_none=True))
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
    except Exception as e:
        logger.exception("WebSocket error")
        await websocket.send_json({"type": "error", "error": str(e)})
        await websocket.close()


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "agent_ready": _agent is not None,
        "tools_count": len(_agent.tools) if _agent else 0,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
