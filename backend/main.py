import os
import logging
from pathlib import Path
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# 显式加载 .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

from miniclaw import Tool
from miniclaw.agent import Agent, AgentConfig
from miniclaw.claw import Claw
from miniclaw.session_history import (
    PaginatedMessagesResponse,
    SessionCreateResponse,
    SessionListResponse,
)
from miniclaw.system_prompt import build_default_system_prompt
from tools import get_tools

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# 全局实例（由 lifespan 管理）
_claw: Claw | None = None


def get_claw() -> Claw:
    """获取 Claw 实例（FastAPI 依赖）"""
    if _claw is None:
        raise RuntimeError("Claw not initialized")
    return _claw


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global _claw

    logger.info("Initializing Claw...")

    # 初始化 Agent
    backend_dir = Path(__file__).parent
    workspace_root = backend_dir.parent
    config = AgentConfig(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        system_prompt=build_default_system_prompt(
            workspace_root=workspace_root,
            backend_dir=backend_dir,
            frontend_dir=workspace_root / "frontend",
            skills_dir=backend_dir / "skills",
        ),
    )
    agent = Agent(config=config, tools=get_tools())

    # 初始化 Claw（编排层）
    _claw = Claw(agent=agent)
    logger.info("Claw initialized with %d tools", len(agent.tools))

    yield

    logger.info("Shutting down...")
    _claw = None


app = FastAPI(
    title="MiniClaw Agent",
    version="3.0.0",
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
    claw: Claw = Depends(get_claw),
):
    """
    WebSocket 聊天接口

    接收: { session_id, message }
    返回: Event 流
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            session_id = data.get("session_id", "")
            user_message = data.get("message", "").strip()

            if not user_message:
                continue

            # 调用 Claw 完成对话（上下文管理 + Agent 调用）
            async for event in claw.chat(session_id, user_message):
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
        "claw_ready": _claw is not None,
        "tools_count": len(_claw.agent.tools) if _claw else 0,
    }


@app.post("/sessions", response_model=SessionCreateResponse)
async def create_session(claw: Claw = Depends(get_claw)):
    return SessionCreateResponse(session_id=claw.create_session())


@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions(claw: Claw = Depends(get_claw)):
    return SessionListResponse(sessions=claw.list_sessions())


@app.get("/sessions/{session_id}/messages", response_model=PaginatedMessagesResponse)
async def get_session_messages(
    session_id: str,
    before: int | None = Query(default=None, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    claw: Claw = Depends(get_claw),
):
    if not claw.session_manager.session_exists(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return claw.get_messages_page(session_id, before=before, limit=limit)


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str, claw: Claw = Depends(get_claw)):
    if not claw.delete_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True, "session_id": session_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
