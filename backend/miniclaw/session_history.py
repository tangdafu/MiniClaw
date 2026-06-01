"""Session history presentation and pagination helpers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DisplayToolCall(BaseModel):
    name: str = ""
    arguments: str = ""


class DisplayToolPair(BaseModel):
    call: DisplayToolCall
    result: str = ""


class DisplayMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = ""
    reasoning: str | None = None
    toolPairs: list[DisplayToolPair] = Field(default_factory=list)


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


def present_messages(messages: list[dict[str, Any]]) -> list[DisplayMessage]:
    """Convert persisted protocol messages into frontend display messages."""
    display_messages: list[DisplayMessage] = []
    index = 0

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
            tool_calls = message.get("tool_calls") or []
            next_index = index + 1
            tool_results: dict[str, str] = {}

            while next_index < len(messages) and messages[next_index].get("role") == "tool":
                tool_message = messages[next_index]
                tool_call_id = tool_message.get("tool_call_id")
                if tool_call_id:
                    tool_results[str(tool_call_id)] = _string_content(tool_message.get("content", ""))
                next_index += 1

            tool_pairs = [
                DisplayToolPair(
                    call=DisplayToolCall(
                        name=str((tool_call.get("function") or {}).get("name") or ""),
                        arguments=_string_content((tool_call.get("function") or {}).get("arguments", "")),
                    ),
                    result=tool_results.get(str(tool_call.get("id", "")), ""),
                )
                for tool_call in tool_calls
            ]

            display_messages.append(
                DisplayMessage(
                    role="assistant",
                    content=_string_content(message.get("content", "")),
                    reasoning=message.get("reasoning_content") or None,
                    toolPairs=tool_pairs,
                )
            )
            index = max(next_index, index + 1)
            continue

        index += 1

    return display_messages


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
