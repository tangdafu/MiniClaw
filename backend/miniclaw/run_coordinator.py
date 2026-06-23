import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

RunEmit = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class SessionJob:
    session_id: str
    run_id: str
    message: str
    emit: RunEmit
    priority: int = 10
    sequence: int = 0
    status: Literal["queued", "running", "done", "cancelled", "error"] = "queued"
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event, compare=False)


@dataclass(order=True)
class QueuedSessionJob:
    priority: int
    sequence: int
    job: SessionJob = field(compare=False)


RunExecutor = Callable[[SessionJob], Awaitable[None]]


class RunCoordinator:
    def __init__(self, execute_job: RunExecutor):
        self.execute_job = execute_job
        self.session_queues: dict[str, asyncio.PriorityQueue[QueuedSessionJob]] = {}
        self.session_workers: dict[str, asyncio.Task] = {}
        self.session_current_tasks: dict[str, asyncio.Task] = {}
        self.session_current_jobs: dict[str, SessionJob] = {}
        self._sequence = 0

    async def enqueue(
        self,
        session_id: str,
        user_message: str,
        emit: RunEmit,
        priority: int = 10,
    ) -> str:
        self._sequence += 1
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        job = SessionJob(
            session_id=session_id,
            run_id=run_id,
            message=user_message,
            emit=emit,
            priority=priority,
            sequence=self._sequence,
        )
        queue = self._queue_for(session_id)
        await queue.put(QueuedSessionJob(priority=priority, sequence=job.sequence, job=job))
        await emit({
            "type": "queued",
            "session_id": session_id,
            "run_id": run_id,
            "queue_position": queue.qsize(),
            "queued_count": queue.qsize(),
        })
        await self.emit_queue_updated(session_id, emit)
        self._ensure_worker(session_id)
        return run_id

    async def cancel_current(self, session_id: str) -> bool:
        job = self.session_current_jobs.get(session_id)
        if job is not None:
            job.cancel_event.set()
        task = self.session_current_tasks.get(session_id)
        if not task or task.done():
            return False
        task.cancel()
        return True

    async def clear_queue(self, session_id: str, emit: RunEmit | None = None) -> int:
        queue = self.session_queues.get(session_id)
        cleared = self._drain_queue(queue) if queue else 0
        if emit:
            await emit({"type": "queue_cleared", "session_id": session_id, "cleared_count": cleared})
            await self.emit_queue_updated(session_id, emit)
        return cleared

    async def stop_session(self, session_id: str, emit: RunEmit | None = None) -> int:
        cleared = await self.clear_queue(session_id)
        await self.cancel_current(session_id)
        if emit:
            await emit({"type": "session_stopped", "session_id": session_id, "cleared_count": cleared})
            await self.emit_queue_updated(session_id, emit)
        return cleared

    async def stop_all_sessions(self) -> None:
        for session_id in list(set(self.session_queues) | set(self.session_current_tasks)):
            await self.clear_queue(session_id)
            await self.cancel_current(session_id)

    async def emit_queue_updated(self, session_id: str, emit: RunEmit) -> None:
        queue = self.session_queues.get(session_id)
        current = self.session_current_jobs.get(session_id)
        await emit({
            "type": "queue_updated",
            "session_id": session_id,
            "running_run_id": current.run_id if current else "",
            "queued_count": queue.qsize() if queue else 0,
        })

    def _queue_for(self, session_id: str) -> asyncio.PriorityQueue[QueuedSessionJob]:
        queue = self.session_queues.get(session_id)
        if queue is None:
            queue = asyncio.PriorityQueue()
            self.session_queues[session_id] = queue
        return queue

    def _ensure_worker(self, session_id: str) -> None:
        worker = self.session_workers.get(session_id)
        if worker is None or worker.done():
            self.session_workers[session_id] = asyncio.create_task(self._session_worker(session_id))

    async def _session_worker(self, session_id: str) -> None:
        queue = self._queue_for(session_id)
        try:
            while True:
                if queue.empty():
                    break
                queued = await queue.get()
                job = queued.job
                self.session_current_jobs[session_id] = job
                run_task = asyncio.create_task(self.execute_job(job))
                self.session_current_tasks[session_id] = run_task
                await job.emit({"type": "run_started", "session_id": session_id, "run_id": job.run_id})
                await self.emit_queue_updated(session_id, job.emit)
                try:
                    await run_task
                except asyncio.CancelledError:
                    await job.emit({"type": "cancelled", "session_id": session_id, "run_id": job.run_id})
                finally:
                    queue.task_done()
                    self.session_current_tasks.pop(session_id, None)
                    self.session_current_jobs.pop(session_id, None)
                    await self.emit_queue_updated(session_id, job.emit)
        finally:
            self.session_workers.pop(session_id, None)
            if queue.empty():
                self.session_queues.pop(session_id, None)

    def _drain_queue(self, queue: asyncio.PriorityQueue[QueuedSessionJob]) -> int:
        cleared = 0
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            queue.task_done()
            cleared += 1
        return cleared
