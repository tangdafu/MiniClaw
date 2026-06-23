from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
import asyncio

from .types import Tool


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunSummary:
    run_id: str
    session_id: str | None
    status: Literal["running", "done", "cancelled", "error"] = "running"
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    tool_calls_total: int = 0
    tool_calls_blocked: int = 0
    changed_files: list[str] = field(default_factory=list)
    summary_text: str | None = None
    last_error: str | None = None
    commands: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReactContext:
    messages: list[dict]
    user_message: str
    model: str
    max_iterations: int
    tools: list[Tool] = field(default_factory=list)
    system_prompt: str | None = None
    session_id: str | None = None
    iteration: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelRequest:
    model: str
    messages: list[dict]
    tools: list[dict] | None = None
    tool_choice: str | None = None
    stream: bool = True

    def to_kwargs(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": self.messages,
            "tools": self.tools,
            "tool_choice": self.tool_choice,
            "stream": self.stream,
        }


@dataclass
class ModelTurn:
    assistant_message: dict
    tool_calls: list[dict] = field(default_factory=list)
    text: str = ""
    reasoning_content: str = ""


@dataclass
class ToolExecution:
    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    result: str
    error: str | None = None
    session_id: str | None = None
    run_id: str | None = None
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None
    decision: str = "allow"
    blocked_reason: str | None = None
    changed_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str | None = None
    run_id: str | None = None
    session_dir: Path | None = None
    workspace_root: Path | None = None
    cancelled: bool = False
    permissions: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
    cancel_event: asyncio.Event | None = None
