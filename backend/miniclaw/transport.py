from typing import Any

from .runtime_events import RuntimeEvent
from .types import Event


def project_event(event: Event | RuntimeEvent, session_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    if isinstance(event, RuntimeEvent):
        payload = {"type": event.type, **event.data}
        session_id = session_id if session_id is not None else event.session_id
        run_id = run_id if run_id is not None else event.run_id
    else:
        payload = event.model_dump(exclude_none=True)
    if session_id is not None:
        payload["session_id"] = session_id
    if run_id is not None:
        payload["run_id"] = run_id
    return payload
