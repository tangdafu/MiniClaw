import asyncio
import logging
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import AsyncIterator, Protocol

from .types import Event
from .tool_pruning import restored_pruning_records

logger = logging.getLogger(__name__)


class SessionRepository(Protocol):
    def load_messages(self, session_id: str) -> list[dict]: ...
    def save_messages(self, session_id: str, messages: list[dict]) -> None: ...
    def get_session_path(self, session_id: str) -> Path: ...
    def save_run_summary(self, session_id: str, run_id: str, summary: dict) -> None: ...


class ChatAgent(Protocol):
    async def chat(
        self,
        messages: list[dict],
        user_message: str,
        session_dir: Path | None = None,
        run_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]: ...


class ConversationService:
    def __init__(self, agent: ChatAgent, session_manager: SessionRepository):
        self.agent = agent
        self.session_manager = session_manager

    async def chat(
        self,
        session_id: str,
        user_message: str,
        run_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        logger.info("Session %s: user message received", session_id)
        messages = self.session_manager.load_messages(session_id)
        session_dir = self.session_manager.get_session_path(session_id)
        try:
            async for event in self.agent.chat(
                messages,
                user_message,
                session_dir=session_dir,
                run_id=run_id,
                cancel_event=cancel_event,
            ):
                yield event
        except asyncio.CancelledError:
            self.session_manager.save_messages(session_id, messages)
            self._save_run_summary(session_id, run_id)
            raise
        except Exception:
            self.session_manager.save_messages(session_id, messages)
            self._save_run_summary(session_id, run_id)
            raise
        else:
            self.session_manager.save_messages(session_id, messages)
            self._save_run_summary(session_id, run_id)
            logger.info("Session %s: conversation saved", session_id)

    def _save_run_summary(self, session_id: str, run_id: str | None) -> None:
        if not run_id:
            return
        runtime = getattr(self.agent, "runtime", None)
        summary = getattr(runtime, "last_run_summary", None)
        if summary is None:
            return
        if is_dataclass(summary):
            payload = asdict(summary)
        elif isinstance(summary, dict):
            payload = dict(summary)
        else:
            return
        payload.setdefault("run_id", run_id)
        payload.setdefault("session_id", session_id)
        self.session_manager.save_run_summary(session_id, run_id, payload)

    def get_context_usage(self, session_id: str) -> Event:
        messages = self.session_manager.load_messages(session_id)
        session_dir = self.session_manager.get_session_path(session_id)
        compressor = getattr(getattr(self.agent, "runtime", None), "context_compressor", None)
        if compressor is None:
            raise RuntimeError("Context compressor is not available")
        event = compressor.usage_for_saved_messages(messages, session_dir=session_dir)
        keep_tokens = getattr(getattr(compressor, "tool_pruner", None), "config", None)
        event.data["pruning_records"] = restored_pruning_records(
            session_dir,
            keep_tokens=getattr(keep_tokens, "keep_tokens", 2_000),
        )
        return event

    def session_dir(self, session_id: str) -> Path:
        return self.session_manager.get_session_path(session_id)
