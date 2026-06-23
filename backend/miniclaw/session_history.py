"""Session history presentation and pagination helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DisplayToolCall(BaseModel):
    name: str = ""
    arguments: str = ""
    toolCallId: str | None = None
    status: Literal["pending", "running", "blocked", "completed"] | None = None
    decision: Literal["allow", "deny", "confirm"] | None = None
    blockedReason: str | None = None
    startedAt: str | None = None
    finishedAt: str | None = None
    changedFiles: list[str] = Field(default_factory=list)


class DisplayToolPair(BaseModel):
    call: DisplayToolCall
    result: str = ""


class DisplayMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = ""
    reasoning: str | None = None
    toolPairs: list[DisplayToolPair] = Field(default_factory=list)
    runId: str | None = None
    status: Literal["queued", "running", "cancelling", "cancelled", "done", "error"] | None = None
    runSummary: dict[str, Any] | None = None


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class SessionCreateResponse(BaseModel):
    session_id: str


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]


class PaginatedMessagesResponse(BaseModel):
    items: list[DisplayMessage]
    next_before: int | None
    has_more: bool
    total: int


def present_messages(messages: list[dict[str, Any]], run_summaries: dict[str, dict] | None = None) -> list[DisplayMessage]:
    """Convert persisted protocol messages into frontend display messages."""
    display_messages: list[DisplayMessage] = []
    index = 0
    summaries = run_summaries or {}

    while index < len(messages):
        message = messages[index]
        role = message.get("role")

        if role == "user":
            display_messages.append(
                DisplayMessage(role="user", content=_string_content(message.get("content", "")))
            )
            index += 1
            continue

        if role == "assistant":
            display_message, index = _present_assistant_turn(messages, index, summaries)
            display_messages.append(display_message)
            continue

        index += 1

    return display_messages


def _present_assistant_turn(
    messages: list[dict[str, Any]],
    start_index: int,
    run_summaries: dict[str, dict],
) -> tuple[DisplayMessage, int]:
    """Group a persisted ReAct assistant/tool chain into one frontend bubble."""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_pairs: list[DisplayToolPair] = []
    index = start_index
    run_id: str | None = None

    while index < len(messages) and messages[index].get("role") == "assistant":
        message = messages[index]
        content = _string_content(message.get("content", ""))
        reasoning = _string_content(message.get("reasoning_content", ""))
        tool_calls = message.get("tool_calls") or []
        run_id = run_id or _string_content(message.get("run_id") or "") or None

        if content:
            content_parts.append(content)
        if reasoning:
            reasoning_parts.append(reasoning)

        index += 1
        tool_results: dict[str, dict[str, Any]] = {}
        while index < len(messages) and messages[index].get("role") == "tool":
            tool_message = messages[index]
            tool_call_id = tool_message.get("tool_call_id")
            if tool_call_id:
                tool_results[str(tool_call_id)] = {
                    "content": _string_content(tool_message.get("content", "")),
                    "decision": tool_message.get("decision"),
                    "blocked_reason": tool_message.get("blocked_reason"),
                    "changed_files": tool_message.get("changed_files") or [],
                    "started_at": tool_message.get("started_at"),
                    "finished_at": tool_message.get("finished_at"),
                }
            index += 1

        tool_pairs.extend(
            DisplayToolPair(
                call=DisplayToolCall(
                    name=str((tool_call.get("function") or {}).get("name") or ""),
                    arguments=_string_content((tool_call.get("function") or {}).get("arguments", "")),
                    toolCallId=str(tool_call.get("id") or "") or None,
                    status="blocked" if tool_results.get(str(tool_call.get("id", "")), {}).get("decision") != "allow" else "completed",
                    decision=tool_results.get(str(tool_call.get("id", "")), {}).get("decision"),
                    blockedReason=tool_results.get(str(tool_call.get("id", "")), {}).get("blocked_reason"),
                    startedAt=tool_results.get(str(tool_call.get("id", "")), {}).get("started_at"),
                    finishedAt=tool_results.get(str(tool_call.get("id", "")), {}).get("finished_at"),
                    changedFiles=[str(path) for path in tool_results.get(str(tool_call.get("id", "")), {}).get("changed_files", [])],
                ),
                result=tool_results.get(str(tool_call.get("id", "")), {}).get("content", ""),
            )
            for tool_call in tool_calls
        )

        if not tool_calls:
            break

    run_summary = run_summaries.get(run_id or "") if run_id else None
    status = None
    if isinstance(run_summary, dict):
        summary_status = run_summary.get("status")
        if summary_status in {"queued", "running", "cancelling", "cancelled", "done", "error"}:
            status = summary_status

    return (
        DisplayMessage(
            role="assistant",
            content="\n\n".join(content_parts),
            reasoning="\n".join(reasoning_parts) or None,
            toolPairs=tool_pairs,
            runId=run_id,
            status=status,
            runSummary=run_summary,
        ),
        index,
    )


def paginate_display_messages(
    messages: list[DisplayMessage], before: int | None = None, limit: int = 20
) -> PaginatedMessagesResponse:
    total = len(messages)
    safe_limit = max(1, min(limit, 100))
    end = total if before is None else max(0, min(before, total))
    start = max(0, end - safe_limit)
    items = messages[start:end]
    next_before = start if start > 0 else None

    return PaginatedMessagesResponse(
        items=items,
        next_before=next_before,
        has_more=start > 0,
        total=total,
    )


def _string_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)
