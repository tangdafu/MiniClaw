from .react_context import ModelRequest, ModelTurn, ReactContext, ToolExecution


class BaseHook:
    async def on_run_start(self, ctx: ReactContext) -> None:
        pass

    async def on_user_message(self, ctx: ReactContext) -> None:
        pass

    async def before_iteration(self, ctx: ReactContext) -> None:
        pass

    async def before_build_messages(self, ctx: ReactContext) -> None:
        pass

    async def after_build_messages(self, ctx: ReactContext, messages: list[dict]) -> None:
        pass

    async def before_model_call(self, ctx: ReactContext, request: ModelRequest) -> None:
        pass

    async def after_model_stream(self, ctx: ReactContext, turn: ModelTurn) -> None:
        pass

    async def after_assistant_message(self, ctx: ReactContext, message: dict) -> None:
        pass

    async def before_tool_call(self, ctx: ReactContext, tool_call: dict) -> None:
        pass

    async def after_tool_call(self, ctx: ReactContext, execution: ToolExecution) -> None:
        pass

    async def before_next_iteration(self, ctx: ReactContext) -> None:
        pass

    async def before_save(self, ctx: ReactContext) -> None:
        pass

    async def on_run_end(self, ctx: ReactContext) -> None:
        pass

    async def on_error(self, ctx: ReactContext, error: Exception) -> None:
        pass


class HookManager:
    def __init__(self, hooks: list[BaseHook] | None = None):
        self.hooks = hooks or []

    async def on_run_start(self, ctx: ReactContext) -> None:
        for hook in self.hooks:
            await hook.on_run_start(ctx)

    async def on_user_message(self, ctx: ReactContext) -> None:
        for hook in self.hooks:
            await hook.on_user_message(ctx)

    async def before_iteration(self, ctx: ReactContext) -> None:
        for hook in self.hooks:
            await hook.before_iteration(ctx)

    async def before_build_messages(self, ctx: ReactContext) -> None:
        for hook in self.hooks:
            await hook.before_build_messages(ctx)

    async def after_build_messages(self, ctx: ReactContext, messages: list[dict]) -> None:
        for hook in self.hooks:
            await hook.after_build_messages(ctx, messages)

    async def before_model_call(self, ctx: ReactContext, request: ModelRequest) -> None:
        for hook in self.hooks:
            await hook.before_model_call(ctx, request)

    async def after_model_stream(self, ctx: ReactContext, turn: ModelTurn) -> None:
        for hook in self.hooks:
            await hook.after_model_stream(ctx, turn)

    async def after_assistant_message(self, ctx: ReactContext, message: dict) -> None:
        for hook in self.hooks:
            await hook.after_assistant_message(ctx, message)

    async def before_tool_call(self, ctx: ReactContext, tool_call: dict) -> None:
        for hook in self.hooks:
            await hook.before_tool_call(ctx, tool_call)

    async def after_tool_call(self, ctx: ReactContext, execution: ToolExecution) -> None:
        for hook in self.hooks:
            await hook.after_tool_call(ctx, execution)

    async def before_next_iteration(self, ctx: ReactContext) -> None:
        for hook in self.hooks:
            await hook.before_next_iteration(ctx)

    async def before_save(self, ctx: ReactContext) -> None:
        for hook in self.hooks:
            await hook.before_save(ctx)

    async def on_run_end(self, ctx: ReactContext) -> None:
        for hook in self.hooks:
            await hook.on_run_end(ctx)

    async def on_error(self, ctx: ReactContext, error: Exception) -> None:
        for hook in self.hooks:
            await hook.on_error(ctx, error)
