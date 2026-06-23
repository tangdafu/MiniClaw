import asyncio
import logging
from typing import AsyncIterator, Awaitable, Callable

from openai import AsyncOpenAI

from pathlib import Path

from .context_compression import ContextCompressionService, PreparedContext
from .hooks import BaseHook, HookManager
from .model_gateway import ChatModelGateway, OpenAIChatModelGateway
from .react_context import ModelRequest, ReactContext, RunSummary, ToolExecution, ToolExecutionContext, utc_now_iso
from .stream import StreamAccumulator
from .tool_executor import PreparedToolCall, ToolExecutor
from .types import Event, Tool, ToolPermissionRequest

logger = logging.getLogger(__name__)


class ReactRuntime:
    def __init__(
            self,
            client: AsyncOpenAI,
            model: str,
            tools: list[Tool] | None = None,
            system_prompt: str | None = None,
            max_iterations: int = 20,
            context_compression=None,
            hooks: list[BaseHook] | HookManager | None = None,
            model_gateway: ChatModelGateway | None = None,
            request_tool_permission: Callable[..., Awaitable[str]] | None = None,
            get_session_tool_policy: Callable[[str, str], str | None] | None = None,
    ):
        self.client = client
        self.model_gateway = model_gateway or OpenAIChatModelGateway(client)
        self.model = model
        self.tools = tools or []
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.context_compression_config = context_compression
        self.context_compressor = ContextCompressionService(
            client=self.client,
            model=self.model,
            system_prompt=self.system_prompt,
            trigger_tokens=context_compression.trigger_tokens,
            target_tokens=context_compression.target_tokens,
            summary_target_tokens=context_compression.summary_target_tokens,
            compression_model=context_compression.compression_model,
            tool_result_pruning=context_compression.tool_result_pruning,
        )
        self.hooks = hooks if isinstance(hooks, HookManager) else HookManager(hooks)
        self.tool_executor = ToolExecutor(self.tools)
        self.request_tool_permission = request_tool_permission
        self.get_session_tool_policy = get_session_tool_policy
        self.last_run_summary: RunSummary | None = None

    async def run(
        self,
        messages: list[dict],
        user_message: str,
        session_dir: Path | None = None,
        run_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]:
        ctx = ReactContext(
            messages=messages,
            user_message=user_message,
            model=self.model,
            max_iterations=self.max_iterations,
            tools=self.tools,
            system_prompt=self.system_prompt,
            session_id=session_dir.name if session_dir else None,
            metadata={"run_id": run_id} if run_id is not None else {},
            state={
                "run_summary": RunSummary(
                    run_id=run_id or "",
                    session_id=session_dir.name if session_dir else None,
                )
            },
        )
        self.last_run_summary = None

        try:
            await self._start_run(ctx, cancel_event)

            while ctx.iteration < ctx.max_iterations:
                self._raise_if_cancelled(cancel_event)
                ctx.iteration += 1
                await self.hooks.before_iteration(ctx)

                model_messages = await self._prepare_context_for_iteration(ctx, session_dir)
                request = self._build_model_request(ctx, model_messages)
                await self.hooks.before_model_call(ctx, request)
                turn, stream_events = await self._stream_model_turn(ctx, request, run_id, cancel_event)
                for event in stream_events:
                    yield event

                if not turn.tool_calls:
                    async for event in self._finalize_success(ctx, turn, session_dir):
                        yield event
                    return

                async for event in self._execute_tool_calls(ctx, turn, session_dir, run_id, cancel_event):
                    yield event

                await self.hooks.before_next_iteration(ctx)

            async for event in self._finalize_max_iterations(ctx):
                yield event

        except asyncio.CancelledError:
            self._finalize_cancelled(ctx)
            raise
        except Exception as exc:
            async for event in self._finalize_error(ctx, exc):
                yield event

    async def _start_run(self, ctx: ReactContext, cancel_event: asyncio.Event | None) -> None:
        self._raise_if_cancelled(cancel_event)
        await self.hooks.on_run_start(ctx)
        ctx.messages.append({"role": "user", "content": ctx.user_message})
        await self.hooks.on_user_message(ctx)

    async def _prepare_context_for_iteration(
        self,
        ctx: ReactContext,
        session_dir: Path | None,
    ) -> list[dict]:
        await self.hooks.before_build_messages(ctx)
        model_messages = None
        async for item in self._build_messages(ctx, session_dir):
            if isinstance(item, PreparedContext):
                model_messages = item.messages
        if model_messages is None:
            raise RuntimeError("Context preparation did not produce model messages")
        await self.hooks.after_build_messages(ctx, model_messages)
        return model_messages

    def _build_model_request(self, ctx: ReactContext, model_messages: list[dict]) -> ModelRequest:
        return ModelRequest(
            model=ctx.model,
            messages=model_messages,
            tools=self._get_tool_schemas(ctx),
            tool_choice="auto" if ctx.tools else None,
            stream=True,
        )

    async def _stream_model_turn(
        self,
        ctx: ReactContext,
        request: ModelRequest,
        run_id: str | None,
        cancel_event: asyncio.Event | None,
    ):
        response = await self.model_gateway.create_chat_completion(**request.to_kwargs())

        accumulator = StreamAccumulator()
        stream_events: list[Event] = []
        async for chunk in response:
            self._raise_if_cancelled(cancel_event)
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            for event in accumulator.feed_delta(delta):
                self._raise_if_cancelled(cancel_event)
                stream_events.append(event)

        turn = accumulator.to_turn()
        turn.assistant_message["run_id"] = run_id
        await self.hooks.after_model_stream(ctx, turn)
        ctx.messages.append(turn.assistant_message)
        await self.hooks.after_assistant_message(ctx, turn.assistant_message)
        return turn, stream_events

    async def _execute_tool_calls(
        self,
        ctx: ReactContext,
        turn,
        session_dir: Path | None,
        run_id: str | None,
        cancel_event: asyncio.Event | None,
    ) -> AsyncIterator[Event]:
        for tool_call in turn.tool_calls:
            self._raise_if_cancelled(cancel_event)
            await self.hooks.before_tool_call(ctx, tool_call)

            prepared = self.tool_executor.prepare(
                tool_call,
                context=ToolExecutionContext(
                    session_id=ctx.session_id,
                    run_id=run_id,
                    session_dir=session_dir,
                    workspace_root=session_dir.parent.parent if session_dir else None,
                    cancel_event=cancel_event,
                ),
            )
            yield Event.create(
                "tool_call",
                name=prepared.tool_name,
                arguments=prepared.arguments_text,
                tool_call_id=prepared.tool_call_id,
            )

            self._raise_if_cancelled(cancel_event)
            permission_request = self._build_permission_request(ctx, prepared, run_id)
            if permission_request is not None:
                yield Event.tool_permission_request(
                    request_id=permission_request.request_id,
                    tool_call_id=permission_request.tool_call_id,
                    tool_name=permission_request.tool_name,
                    arguments=permission_request.arguments_text,
                    category=permission_request.category,
                    risk_level=permission_request.risk_level,
                    reason=permission_request.reason,
                    policy=permission_request.policy,
                    created_at=permission_request.created_at,
                )
            execution = await self._execute_with_permission(
                ctx,
                prepared,
                session_dir=session_dir,
                run_id=run_id,
                cancel_event=cancel_event,
                permission_request=permission_request,
            )
            self._record_tool_execution(ctx, execution)

            self._raise_if_cancelled(cancel_event)
            yield Event.create(
                "tool_result",
                name=execution.name,
                result=execution.result,
                tool_call_id=execution.tool_call_id,
                decision=execution.decision,
                blocked_reason=execution.blocked_reason,
                changed_files=execution.changed_files,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
            )

            ctx.messages.append({
                "role": "tool",
                "tool_call_id": execution.tool_call_id,
                "content": execution.result,
                "decision": execution.decision,
                "blocked_reason": execution.blocked_reason,
                "changed_files": execution.changed_files,
                "started_at": execution.started_at,
                "finished_at": execution.finished_at,
                "run_id": run_id,
            })

            await self.hooks.after_tool_call(ctx, execution)

    async def _finalize_success(
        self,
        ctx: ReactContext,
        turn,
        session_dir: Path | None,
    ) -> AsyncIterator[Event]:
        summary = self._run_summary(ctx)
        summary.status = "done"
        summary.finished_at = utc_now_iso()
        summary.summary_text = turn.text or None
        self.last_run_summary = summary
        yield self.context_compressor.usage_for_saved_messages(ctx.messages, session_dir=session_dir)
        await self.hooks.before_save(ctx)
        await self.hooks.on_run_end(ctx)
        yield Event.done()

    async def _finalize_max_iterations(self, ctx: ReactContext) -> AsyncIterator[Event]:
        summary = self._run_summary(ctx)
        summary.status = "done"
        summary.finished_at = utc_now_iso()
        summary.summary_text = "达到最大迭代次数，对话结束"
        self.last_run_summary = summary
        yield Event.text("\n\n[达到最大迭代次数，对话结束]")
        await self.hooks.before_save(ctx)
        await self.hooks.on_run_end(ctx)
        yield Event.done()

    def _finalize_cancelled(self, ctx: ReactContext) -> None:
        summary = self._run_summary(ctx)
        summary.status = "cancelled"
        summary.finished_at = utc_now_iso()
        if summary.summary_text is None:
            summary.summary_text = "运行已取消"
        self.last_run_summary = summary

    async def _finalize_error(self, ctx: ReactContext, exc: Exception) -> AsyncIterator[Event]:
        logger.exception("React runtime error")
        summary = self._run_summary(ctx)
        summary.status = "error"
        summary.finished_at = utc_now_iso()
        summary.last_error = str(exc)
        if summary.summary_text is None:
            summary.summary_text = str(exc)
        self.last_run_summary = summary
        await self.hooks.on_error(ctx, exc)
        yield Event.error(str(exc))

    def _build_permission_request(
        self,
        ctx: ReactContext,
        prepared: PreparedToolCall,
        run_id: str | None,
    ) -> ToolPermissionRequest | None:
        if prepared.decision.action != "confirm" or prepared.tool is None or self.request_tool_permission is None:
            return None
        if self.get_session_tool_policy is not None and ctx.session_id:
            session_policy = self.get_session_tool_policy(ctx.session_id, prepared.tool_name)
            if session_policy is not None:
                return None
        return ToolPermissionRequest(
            request_id=f"perm_{prepared.tool_call_id or prepared.tool_name}",
            session_id=ctx.session_id or "",
            run_id=run_id or "",
            tool_call_id=prepared.tool_call_id,
            tool_name=prepared.tool_name,
            arguments=prepared.arguments,
            arguments_text=prepared.arguments_text,
            category=prepared.tool.category,
            risk_level=prepared.tool.risk_level,
            reason=prepared.decision.reason,
            policy=prepared.decision.policy,
            created_at=utc_now_iso(),
        )

    async def _execute_with_permission(
        self,
        ctx: ReactContext,
        prepared: PreparedToolCall,
        session_dir: Path | None,
        run_id: str | None,
        cancel_event: asyncio.Event | None,
        permission_request: ToolPermissionRequest | None,
    ) -> ToolExecution:
        context = ToolExecutionContext(
            session_id=ctx.session_id,
            run_id=run_id,
            session_dir=session_dir,
            workspace_root=session_dir.parent.parent if session_dir else None,
            cancel_event=cancel_event,
        )
        if self.get_session_tool_policy is not None and ctx.session_id and prepared.tool is not None:
            session_policy = self.get_session_tool_policy(ctx.session_id, prepared.tool_name)
            if session_policy == "allow":
                return await self.tool_executor.execute_prepared(prepared, context=context, force_allow=True)
            if session_policy == "deny":
                return ToolExecution(
                    tool_call_id=prepared.tool_call_id,
                    name=prepared.tool_name,
                    arguments=prepared.arguments,
                    result=f"[已阻止] 当前会话策略已拒绝工具 {prepared.tool_name} 的执行",
                    error="session_policy_denied",
                    session_id=context.session_id,
                    run_id=context.run_id,
                    started_at=prepared.started_at,
                    finished_at=utc_now_iso(),
                    decision="deny",
                    blocked_reason="session_policy_denied",
                )
        if permission_request is not None and self.request_tool_permission is not None:
            decision = await self.request_tool_permission(permission_request)
            if decision in {"deny_once", "deny_session"}:
                blocked_reason = "session_policy_denied" if decision == "deny_session" else "user_denied"
                result = (
                    f"[已阻止] 当前会话策略已拒绝工具 {prepared.tool_name} 的执行"
                    if decision == "deny_session"
                    else f"[已阻止] 工具 {prepared.tool_name} 被用户拒绝执行"
                )
                return ToolExecution(
                    tool_call_id=prepared.tool_call_id,
                    name=prepared.tool_name,
                    arguments=prepared.arguments,
                    result=result,
                    error=blocked_reason,
                    session_id=context.session_id,
                    run_id=context.run_id,
                    started_at=prepared.started_at,
                    finished_at=utc_now_iso(),
                    decision="deny",
                    blocked_reason=blocked_reason,
                )
            return await self.tool_executor.execute_prepared(prepared, context=context, force_allow=True)
        if prepared.decision.action != "allow":
            return self.tool_executor._prepared_to_execution(prepared, context)
        return await self.tool_executor.execute_prepared(prepared, context=context)

    async def _build_messages(
        self,
        ctx: ReactContext,
        session_dir: Path | None,
    ) -> AsyncIterator[Event | PreparedContext]:
        async for item in self.context_compressor.prepare(ctx.messages, session_dir=session_dir):
            yield item

    def _raise_if_cancelled(self, cancel_event: asyncio.Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError()

    def _run_summary(self, ctx: ReactContext) -> RunSummary:
        summary = ctx.state.get("run_summary")
        if not isinstance(summary, RunSummary):
            summary = RunSummary(
                run_id=str(ctx.metadata.get("run_id") or ""),
                session_id=ctx.session_id,
            )
            ctx.state["run_summary"] = summary
        return summary

    def _record_tool_execution(self, ctx: ReactContext, execution) -> None:
        summary = self._run_summary(ctx)
        summary.tool_calls_total += 1
        if execution.decision != "allow":
            summary.tool_calls_blocked += 1
        for path in execution.changed_files:
            if path not in summary.changed_files:
                summary.changed_files.append(path)
        if execution.name == "execute_command":
            summary.commands.append(
                {
                    "command": execution.arguments.get("command", ""),
                    "workdir": execution.arguments.get("workdir"),
                    "decision": execution.decision,
                }
            )
        if execution.blocked_reason and summary.summary_text is None:
            summary.summary_text = execution.result

    def _get_tool_schemas(self, ctx: ReactContext) -> list[dict] | None:
        visible_tools = [tool for tool in ctx.tools if tool.visibility == "model"]
        if not visible_tools:
            return None
        return [tool.to_openai_schema() for tool in visible_tools]

    def _dump_arguments(self, arguments: dict) -> str:
        import json

        return json.dumps(arguments, ensure_ascii=False)
