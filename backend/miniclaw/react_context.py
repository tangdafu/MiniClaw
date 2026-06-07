from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import Tool


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


@dataclass(frozen=True)
class ToolExecutionContext:
    session_id: str | None = None
    run_id: str | None = None
    session_dir: Path | None = None
    workspace_root: Path | None = None
    cancelled: bool = False
    permissions: dict[str, Any] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)
