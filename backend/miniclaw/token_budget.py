import json
import re
from typing import Any


CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    non_cjk = max(0, len(text) - cjk)
    return max(1, cjk + (non_cjk + 3) // 4)


def estimate_message_tokens(message: dict[str, Any]) -> int:
    total = 4
    total += estimate_text_tokens(str(message.get("role", "")))
    content = message.get("content", "")
    if isinstance(content, str):
        total += estimate_text_tokens(content)
    else:
        total += estimate_text_tokens(json.dumps(content, ensure_ascii=False))
    if message.get("reasoning_content"):
        total += estimate_text_tokens(str(message["reasoning_content"]))
    if message.get("tool_call_id"):
        total += estimate_text_tokens(str(message["tool_call_id"]))
    if message.get("tool_calls"):
        total += estimate_text_tokens(json.dumps(message["tool_calls"], ensure_ascii=False, sort_keys=True))
    return total


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(estimate_message_tokens(message) for message in messages)
