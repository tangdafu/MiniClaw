"""Deprecated runtime event definitions.

This module is currently not used by the active MiniClaw runtime pipeline.
Keep it only as a temporary placeholder until the event model is either
fully adopted or removed in a later cleanup wave.
"""

from dataclasses import dataclass, field
from typing import Any, Literal


RuntimeEventType = Literal[
    "run_started",
    "context_prepared",
    "model_request_prepared",
    "model_delta",
    "tool_call_started",
    "tool_call_completed",
    "iteration_completed",
    "run_completed",
    "run_failed",
]


@dataclass(frozen=True)
class RuntimeEvent:
    type: RuntimeEventType
    session_id: str | None = None
    run_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


def runtime_event(
    event_type: RuntimeEventType,
    *,
    session_id: str | None = None,
    run_id: str | None = None,
    **data: Any,
) -> RuntimeEvent:
    return RuntimeEvent(type=event_type, session_id=session_id, run_id=run_id, data=data)
