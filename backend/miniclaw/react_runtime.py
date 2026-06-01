import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from .context_assembler import ContextAssembler
from .hooks import BaseHook, HookManager
from .react_context import ModelRequest, ReactContext
from .stream import StreamAccumulator
from .tool_executor import ToolExecutor
from .types import Event, Tool

logger = logging.getLogger(__name__)


class ReactRuntime:
    def __init__(
            self,
            client: AsyncOpenAI,
            model: str,
            tools: list[Tool] | None = None,
            system_prompt: str | None = None,
            max_iterations: int = 20,
            context_window_size: int = 20,
            hooks: list[BaseHook] | HookManager | None = None,
    ):
        self.client = client
        self.model = model
        self.tools = tools or []
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.context_window_size = context_window_size
        self.context_assembler = ContextAssembler(
            system_prompt=self.system_prompt,
            window_size=self.context_window_size,
        )
        self.hooks = hooks if isinstance(hooks, HookManager) else HookManager(hooks)
        self.tool_executor = ToolExecutor(self.tools)

    async def run(self, messages: list[dict], user_message: str) -> AsyncIterator[Event]:
        ctx = ReactContext(
            messages=messages,
            user_message=user_message,
            model=self.model,
            max_iterations=self.max_iterations,
            tools=self.tools,
            system_prompt=self.system_prompt,
        )

        try:
            await self.hooks.on_run_start(ctx)

            ctx.messages.append({"role": "user", "content": ctx.user_message})
            await self.hooks.on_user_message(ctx)

            while ctx.iteration < ctx.max_iterations:
                ctx.iteration += 1
                await self.hooks.before_iteration(ctx)

                await self.hooks.before_build_messages(ctx)
                model_messages = self._build_messages(ctx)
                await self.hooks.after_build_messages(ctx, model_messages)

                request = ModelRequest(
                    model=ctx.model,
                    messages=model_messages,
                    tools=self._get_tool_schemas(ctx),
                    tool_choice="auto" if ctx.tools else None,
                    stream=True,
                )
                await self.hooks.before_model_call(ctx, request)

                response = await self.client.chat.completions.create(**request.to_kwargs())

                accumulator = StreamAccumulator()
                async for chunk in response:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta
                    for event in accumulator.feed_delta(delta):
                        yield event

                turn = accumulator.to_turn()
                await self.hooks.after_model_stream(ctx, turn)

                ctx.messages.append(turn.assistant_message)
                await self.hooks.after_assistant_message(ctx, turn.assistant_message)

                if not turn.tool_calls:
                    await self.hooks.before_save(ctx)
                    await self.hooks.on_run_end(ctx)
                    yield Event.done()
                    return

                for tool_call in turn.tool_calls:
                    await self.hooks.before_tool_call(ctx, tool_call)

                    execution = await self.tool_executor.execute(tool_call)

                    yield Event.tool_call(
                        execution.name,
                        self._dump_arguments(execution.arguments),
                    )
                    yield Event.tool_result(execution.name, execution.result)

                    ctx.messages.append({
                        "role": "tool",
                        "tool_call_id": execution.tool_call_id,
                        "content": execution.result,
                    })

                    await self.hooks.after_tool_call(ctx, execution)

                await self.hooks.before_next_iteration(ctx)

            yield Event.text("\n\n[达到最大迭代次数，对话结束]")
            await self.hooks.before_save(ctx)
            await self.hooks.on_run_end(ctx)
            yield Event.done()

        except Exception as exc:
            logger.exception("React runtime error")
            await self.hooks.on_error(ctx, exc)
            yield Event.error(str(exc))

    def _build_messages(self, ctx: ReactContext) -> list[dict]:
        return self.context_assembler.build(ctx.messages)

    def _get_tool_schemas(self, ctx: ReactContext) -> list[dict] | None:
        if not ctx.tools:
            return None
        return [tool.to_openai_schema() for tool in ctx.tools]

    def _dump_arguments(self, arguments: dict) -> str:
        import json

        return json.dumps(arguments, ensure_ascii=False)
