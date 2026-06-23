from typing import Any

from .types import Event


def project_event(event: Event, session_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    payload = event.model_dump(exclude_none=True)
    if session_id is not None:
        payload["session_id"] = session_id
    if run_id is not None:
        payload["run_id"] = run_id
    return payload
