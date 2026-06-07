import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator, Protocol

from .types import Event

logger = logging.getLogger(__name__)


class SessionRepository(Protocol):
    def load_messages(self, session_id: str) -> list[dict]: ...
    def save_messages(self, session_id: str, messages: list[dict]) -> None: ...
    def get_session_path(self, session_id: str) -> Path: ...


class ChatAgent(Protocol):
    async def chat(
        self,
        messages: list[dict],
        user_message: str,
        session_dir: Path | None = None,
    ) -> AsyncIterator[Event]: ...


class ConversationService:
    def __init__(self, agent: ChatAgent, session_manager: SessionRepository):
        self.agent = agent
        self.session_manager = session_manager

    async def chat(self, session_id: str, user_message: str) -> AsyncIterator[Event]:
        logger.info("Session %s: user message received", session_id)
        messages = self.session_manager.load_messages(session_id)
        session_dir = self.session_manager.get_session_path(session_id)
        try:
            async for event in self.agent.chat(messages, user_message, session_dir=session_dir):
                yield event
        except asyncio.CancelledError:
            self.session_manager.save_messages(session_id, messages)
            raise
        else:
            self.session_manager.save_messages(session_id, messages)
            logger.info("Session %s: conversation saved", session_id)

    def get_context_usage(self, session_id: str) -> Event:
        messages = self.session_manager.load_messages(session_id)
        session_dir = self.session_manager.get_session_path(session_id)
        compressor = getattr(getattr(self.agent, "runtime", None), "context_compressor", None)
        if compressor is None:
            raise RuntimeError("Context compressor is not available")
        return compressor.usage_for_saved_messages(messages, session_dir=session_dir)

    def session_dir(self, session_id: str) -> Path:
        return self.session_manager.get_session_path(session_id)
