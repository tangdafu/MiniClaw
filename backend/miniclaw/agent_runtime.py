from pathlib import Path
from typing import AsyncIterator, Protocol

from .types import Event


class AgentRuntime(Protocol):
    async def run(
        self,
        messages: list[dict],
        user_message: str,
        session_dir: Path | None = None,
    ) -> AsyncIterator[Event]: ...
