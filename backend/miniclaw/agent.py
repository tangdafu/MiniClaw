import os
from typing import AsyncIterator

from openai import AsyncOpenAI

from .react_runtime import ReactRuntime
from .stream import ToolCallParser
from .types import Event, Tool


class AgentConfig:
    """Agent 配置"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o",
        max_iterations: int = 20,
        context_window_size: int | None = None,
        system_prompt: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model
        self.max_iterations = max_iterations
        self.context_window_size = context_window_size or self._get_context_window_size()
        self.system_prompt = system_prompt

    def _get_context_window_size(self) -> int:
        value = os.getenv("MINICLAW_CONTEXT_WINDOW_SIZE", "20")
        try:
            size = int(value)
        except ValueError:
            return 20
        return size if size > 0 else 20


class Agent:
    """Public facade for MiniClaw chat runtime."""

    def __init__(self, config: AgentConfig, tools: list[Tool] | None = None):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.max_iterations = config.max_iterations
        self.context_window_size = config.context_window_size
        self.system_prompt = config.system_prompt
        self.tools: list[Tool] = tools or []
        self.runtime = ReactRuntime(
            client=self.client,
            model=self.model,
            tools=self.tools,
            system_prompt=self.system_prompt,
            max_iterations=self.max_iterations,
            context_window_size=self.context_window_size,
        )

    async def chat(self, messages: list[dict], user_message: str) -> AsyncIterator[Event]:
        async for event in self.runtime.run(messages, user_message):
            yield event
