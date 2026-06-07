import os
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from openai import AsyncOpenAI

from .react_runtime import ReactRuntime
from .stream import ToolCallParser
from .types import Event, Tool


@dataclass(frozen=True)
class ContextCompressionConfig:
    trigger_tokens: int = 180_000
    target_tokens: int = 90_000
    summary_target_tokens: int = 8_000
    compression_model: str | None = None

    @classmethod
    def from_env(cls) -> "ContextCompressionConfig":
        return cls(
            trigger_tokens=_positive_int_env("MINICLAW_CONTEXT_COMPACT_TRIGGER_TOKENS", 180_000),
            target_tokens=_positive_int_env("MINICLAW_CONTEXT_COMPACT_TARGET_TOKENS", 90_000),
            summary_target_tokens=_positive_int_env("MINICLAW_CONTEXT_SUMMARY_TARGET_TOKENS", 8_000),
            compression_model=os.getenv("MINICLAW_CONTEXT_COMPRESSION_MODEL") or None,
        )


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


class AgentConfig:
    """Agent 配置"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o",
        max_iterations: int = 20,
        system_prompt: str | None = None,
        context_compression: ContextCompressionConfig | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt
        self.context_compression = context_compression or ContextCompressionConfig.from_env()


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
        self.system_prompt = config.system_prompt
        self.context_compression = config.context_compression
        self.tools: list[Tool] = tools or []
        self.runtime = ReactRuntime(
            client=self.client,
            model=self.model,
            tools=self.tools,
            system_prompt=self.system_prompt,
            max_iterations=self.max_iterations,
            context_compression=self.context_compression,
        )

    async def chat(
        self,
        messages: list[dict],
        user_message: str,
        session_dir: Path | None = None,
    ) -> AsyncIterator[Event]:
        async for event in self.runtime.run(messages, user_message, session_dir=session_dir):
            yield event
