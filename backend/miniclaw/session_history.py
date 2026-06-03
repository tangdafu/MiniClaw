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
            display_message, index = _present_assistant_turn(messages, index)
            display_messages.append(display_message)
            continue

        index += 1

    return display_messages


def _present_assistant_turn(messages: list[dict[str, Any]], start_index: int) -> tuple[DisplayMessage, int]:
    """Group a persisted ReAct assistant/tool chain into one frontend bubble."""
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_pairs: list[DisplayToolPair] = []
    index = start_index

    while index < len(messages) and messages[index].get("role") == "assistant":
        message = messages[index]
        content = _string_content(message.get("content", ""))
        reasoning = _string_content(message.get("reasoning_content", ""))
        tool_calls = message.get("tool_calls") or []

        if content:
            content_parts.append(content)
        if reasoning:
            reasoning_parts.append(reasoning)

        index += 1
        tool_results: dict[str, str] = {}
        while index < len(messages) and messages[index].get("role") == "tool":
            tool_message = messages[index]
            tool_call_id = tool_message.get("tool_call_id")
            if tool_call_id:
                tool_results[str(tool_call_id)] = _string_content(tool_message.get("content", ""))
            index += 1

        tool_pairs.extend(
            DisplayToolPair(
                call=DisplayToolCall(
                    name=str((tool_call.get("function") or {}).get("name") or ""),
                    arguments=_string_content((tool_call.get("function") or {}).get("arguments", "")),
                ),
                result=tool_results.get(str(tool_call.get("id", "")), ""),
            )
            for tool_call in tool_calls
        )

        if not tool_calls:
            break

    return (
        DisplayMessage(
            role="assistant",
            content="\n\n".join(content_parts),
            reasoning="\n".join(reasoning_parts) or None,
            toolPairs=tool_pairs,
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
