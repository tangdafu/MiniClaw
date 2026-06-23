"""MiniClaw Claw — 上下文管理与 Agent 编排层"""

import logging
import asyncio
from typing import AsyncIterator

from .types import Event, PermissionResponseDecision, ToolPermissionRequest
from .agent import Agent
from .conversation import ConversationService
from .run_coordinator import RunCoordinator, RunEmit, SessionJob
from .session_history import PaginatedMessagesResponse, SessionSummary
from .session_store import SessionManager
from .transport import project_event

logger = logging.getLogger(__name__)


class PermissionCoordinator:
    def __init__(self):
        self._pending: dict[str, ToolPermissionRequest] = {}
        self._futures: dict[str, asyncio.Future[str]] = {}
        self._session_policies: dict[str, dict[str, str]] = {}

    def create_request(self, request: ToolPermissionRequest) -> ToolPermissionRequest:
        self._pending[request.request_id] = request
        self._futures[request.request_id] = asyncio.get_running_loop().create_future()
        return request

    async def wait_for_decision(self, request_id: str) -> str:
        future = self._futures.get(request_id)
        if future is None:
            raise RuntimeError("Permission request not found")
        return await future

    def get_session_policy(self, session_id: str, tool_name: str) -> str | None:
        return self._session_policies.get(session_id, {}).get(tool_name)

    def set_session_policy(self, session_id: str, tool_name: str, decision: str) -> None:
        session_rules = self._session_policies.setdefault(session_id, {})
        session_rules[tool_name] = decision

    def resolve(self, request_id: str, decision: PermissionResponseDecision) -> ToolPermissionRequest | None:
        request = self._pending.get(request_id)
        future = self._futures.get(request_id)
        if request is None or future is None:
            return None
        request.status = "approved" if decision in {"allow_once", "allow_session"} else "denied"
        if decision == "allow_session":
            self.set_session_policy(request.session_id, request.tool_name, "allow")
        elif decision == "deny_session":
            self.set_session_policy(request.session_id, request.tool_name, "deny")
        if not future.done():
            future.set_result(decision)
        self._pending.pop(request_id, None)
        self._futures.pop(request_id, None)
        return request

    def clear_session(self, session_id: str) -> None:
        self._session_policies.pop(session_id, None)
        for request_id, request in list(self._pending.items()):
            if request.session_id != session_id:
                continue
            future = self._futures.get(request_id)
            request.status = "expired"
            if future is not None and not future.done():
                future.set_result("deny_once")
            self._pending.pop(request_id, None)
            self._futures.pop(request_id, None)

    def get(self, request_id: str) -> ToolPermissionRequest | None:
        return self._pending.get(request_id)


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
        self.conversation = ConversationService(agent=agent, session_manager=self.session_manager)
        self.run_coordinator = RunCoordinator(self._execute_job)
        self.permission_coordinator = PermissionCoordinator()

    def create_session(self) -> str:
        """创建新会话"""
        return self.session_manager.create_session()

    def list_sessions(self) -> list[SessionSummary]:
        return self.session_manager.list_sessions()

    def delete_session(self, session_id: str) -> bool:
        return self.session_manager.delete_session(session_id)

    def get_messages_page(
        self, session_id: str, before: int | None = None, limit: int = 20
    ) -> PaginatedMessagesResponse:
        return self.session_manager.get_messages_page(session_id, before=before, limit=limit)

    def get_context_usage(self, session_id: str) -> Event:
        return self.conversation.get_context_usage(session_id)

    def get_run_summary(self, session_id: str, run_id: str) -> dict | None:
        return self.session_manager.load_run_summary(session_id, run_id)

    def list_run_summaries(self, session_id: str) -> dict[str, dict]:
        return self.session_manager.list_run_summaries(session_id)

    def create_tool_permission_request(self, request: ToolPermissionRequest) -> ToolPermissionRequest:
        return self.permission_coordinator.create_request(request)

    async def wait_for_tool_permission(self, request_id: str) -> str:
        return await self.permission_coordinator.wait_for_decision(request_id)

    async def request_tool_permission(self, request: ToolPermissionRequest) -> str:
        self.permission_coordinator.create_request(request)
        return await self.permission_coordinator.wait_for_decision(request.request_id)

    def get_session_tool_policy(self, session_id: str, tool_name: str) -> str | None:
        return self.permission_coordinator.get_session_policy(session_id, tool_name)

    def respond_tool_permission(
        self,
        session_id: str,
        request_id: str,
        decision: PermissionResponseDecision,
    ) -> bool:
        request = self.permission_coordinator.get(request_id)
        if request is None or request.session_id != session_id:
            return False
        return self.permission_coordinator.resolve(request_id, decision) is not None

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

        async for event in self.conversation.chat(session_id, user_message):
            yield event

    async def enqueue_chat(
        self,
        session_id: str,
        user_message: str,
        emit: RunEmit,
        priority: int = 10,
    ) -> tuple[str, str]:
        if not session_id or not self.session_manager.session_exists(session_id):
            session_id = self.create_session()
            await emit({"type": "session_created", "session_id": session_id})

        run_id = await self.run_coordinator.enqueue(session_id, user_message, emit, priority=priority)
        return session_id, run_id

    async def cancel_current(self, session_id: str) -> bool:
        return await self.run_coordinator.cancel_current(session_id)

    async def clear_queue(self, session_id: str, emit: RunEmit | None = None) -> int:
        return await self.run_coordinator.clear_queue(session_id, emit)

    async def stop_session(self, session_id: str, emit: RunEmit | None = None) -> int:
        self.permission_coordinator.clear_session(session_id)
        return await self.run_coordinator.stop_session(session_id, emit)

    async def stop_all_sessions(self) -> None:
        for session_id in list(self.run_coordinator.session_queues) + list(self.run_coordinator.session_current_jobs):
            self.permission_coordinator.clear_session(session_id)
        await self.run_coordinator.stop_all_sessions()

    async def _execute_job(self, job: SessionJob) -> None:
        try:
            async for event in self.conversation.chat(
                job.session_id,
                job.message,
                run_id=job.run_id,
                cancel_event=job.cancel_event,
            ):
                await job.emit(project_event(event, job.session_id, job.run_id))
        except Exception as exc:
            logger.exception("Session %s run %s failed", job.session_id, job.run_id)
            await job.emit({
                "type": "error",
                "session_id": job.session_id,
                "run_id": job.run_id,
                "error": str(exc),
            })
        else:
            logger.info("Session %s run %s saved", job.session_id, job.run_id)
