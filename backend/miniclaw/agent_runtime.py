"""Deprecated runtime protocol placeholder.

The active MiniClaw application currently instantiates ReactRuntime directly.
Keep this protocol only as a temporary seam until a real multi-runtime
injection strategy exists.
"""

from pathlib import Path
from typing import AsyncIterator, Protocol
import asyncio

from .types import Event


class AgentRuntime(Protocol):
    async def run(
        self,
        messages: list[dict],
        user_message: str,
        session_dir: Path | None = None,
        run_id: str | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> AsyncIterator[Event]: ...
