"""MiniClaw Claw — 上下文管理与 Agent 编排层"""

import json
import logging
import uuid
from pathlib import Path
from typing import AsyncIterator

from .types import Event
from .agent import Agent

logger = logging.getLogger(__name__)


class SessionManager:
    """会话持久化管理器"""

    def __init__(self, sessions_dir: Path | str | None = None):
        if sessions_dir is None:
            self.sessions_dir = Path(__file__).parent.parent / "sessions"
        else:
            self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> str:
        """创建新会话，返回 session_id"""
        session_id = uuid.uuid4().hex[:12]
        session_path = self.sessions_dir / session_id
        session_path.mkdir(parents=True, exist_ok=True)

        chat_file = session_path / "chat.json"
        chat_file.write_text("[]", encoding="utf-8")

        return session_id

    def get_chat_file(self, session_id: str) -> Path:
        return self.sessions_dir / session_id / "chat.json"

    def session_exists(self, session_id: str) -> bool:
        return self.get_chat_file(session_id).exists()

    def load_messages(self, session_id: str) -> list[dict]:
        """加载会话历史消息"""
        chat_file = self.get_chat_file(session_id)
        if not chat_file.exists():
            return []

        try:
            text = chat_file.read_text(encoding="utf-8")
            if not text.strip():
                return []
            return json.loads(text)
        except (json.JSONDecodeError, Exception):
            return []

    def save_messages(self, session_id: str, messages: list[dict]) -> None:
        """保存完整消息列表"""
        chat_file = self.get_chat_file(session_id)
        chat_file.parent.mkdir(parents=True, exist_ok=True)
        chat_file.write_text(
            json.dumps(messages, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    def append_message(self, session_id: str, message: dict) -> None:
        """追加单条消息"""
        messages = self.load_messages(session_id)
        messages.append(message)
        self.save_messages(session_id, messages)


class Claw:
    """
    MiniClaw Claw — 会话生命周期管理与 Agent 编排

    职责：
    1. 管理会话生命周期（创建、验证）
    2. 加载/保存会话历史（委托 SessionManager）
    3. 调用 Agent 进行对话（Agent 负责消息拼接与工具调用循环）
    4. 流式返回 Event

    使用示例：
        claw = Claw(agent=agent, session_manager=session_manager)
        async for event in claw.chat(session_id, user_message):
            print(event)
    """

    def __init__(self, agent: Agent, session_manager: SessionManager | None = None):
        self.agent = agent
        self.session_manager = session_manager or SessionManager()

    def create_session(self) -> str:
        """创建新会话"""
        return self.session_manager.create_session()

    async def chat(self, session_id: str, user_message: str) -> AsyncIterator[Event]:
        """
        对话入口 — 管理会话生命周期，委托 Agent 处理对话逻辑

        Args:
            session_id: 会话 ID
            user_message: 用户最新输入

        Yields:
            Event: 流式事件（包含 session_created 等控制事件）
        """
        # 如果没有 session_id，创建新会话
        if not session_id or not self.session_manager.session_exists(session_id):
            session_id = self.create_session()
            yield Event.session_created(session_id)

        logger.info("Session %s: user message received", session_id)

        # 加载历史消息（Agent 会原地修改此列表）
        messages = self.session_manager.load_messages(session_id)

        # 调用 Agent（Agent 负责追加 user_message、assistant、tool 消息）
        async for event in self.agent.chat(messages, user_message):
            yield event

        # Agent 已完成对话循环，messages 已包含完整历史
        # 保存更新后的消息列表
        self.session_manager.save_messages(session_id, messages)
        logger.info("Session %s: conversation saved", session_id)
