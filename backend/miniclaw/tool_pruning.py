import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .react_context import ToolExecutionContext
from .token_budget import estimate_messages_tokens, estimate_text_tokens
from .types import Event, Tool


@dataclass(frozen=True)
class ToolResultPruningConfig:
    trigger_tokens: int = 12_000
    keep_tokens: int = 2_000
    total_ratio: float = 0.30
    target_ratio: float = 0.20
    read_max_chars: int = 20_000


@dataclass(frozen=True)
class PrunedToolResultRecord:
    prune_id: str
    message_index: int
    tool_call_id: str
    tool_name: str
    content_hash: str
    original_estimated_tokens: int
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PrunedToolResultRecord":
        return cls(
            prune_id=str(data.get("prune_id", "")),
            message_index=int(data.get("message_index", -1)),
            tool_call_id=str(data.get("tool_call_id", "")),
            tool_name=str(data.get("tool_name", "")),
            content_hash=str(data.get("content_hash", "")),
            original_estimated_tokens=int(data.get("original_estimated_tokens", 0)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "prune_id": self.prune_id,
            "message_index": self.message_index,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "content_hash": self.content_hash,
            "original_estimated_tokens": self.original_estimated_tokens,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class PrunedToolResultIndex:
    version: int
    results: dict[str, PrunedToolResultRecord]

    @classmethod
    def empty(cls) -> "PrunedToolResultIndex":
        return cls(version=1, results={})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PrunedToolResultIndex":
        raw_results = dict(data.get("results") or {})
        return cls(
            version=int(data.get("version", 1)),
            results={key: PrunedToolResultRecord.from_dict({"prune_id": key, **dict(value)}) for key, value in raw_results.items()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "results": {key: record.to_dict() for key, record in self.results.items()},
        }


@dataclass(frozen=True)
class ToolPruningResult:
    messages: list[dict[str, Any]]
    events: list[Event]
    pruned: bool


@dataclass(frozen=True)
class ToolResultCandidate:
    message_index: int
    tool_call_id: str
    tool_name: str
    arguments: str
    content: str
    tokens: int


class PrunedToolResultRepository:
    def __init__(self, session_dir: Path | None):
        self.session_dir = session_dir

    def read_index(self) -> PrunedToolResultIndex:
        path = self._index_path()
        if not path or not path.exists():
            return PrunedToolResultIndex.empty()
        try:
            return PrunedToolResultIndex.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return PrunedToolResultIndex.empty()

    def write_index(self, index: PrunedToolResultIndex) -> None:
        path = self._index_path()
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(index.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def read_result(self, prune_id: str, offset: int = 0, limit: int = 8_000, max_chars: int = 20_000) -> str:
        if not self.session_dir:
            return "[错误] 当前会话不支持读取剪枝工具结果"
        index = self.read_index()
        record = index.results.get(prune_id)
        if not record:
            return f"[错误] 未找到剪枝工具结果: {prune_id}"
        messages = self._load_messages()
        if record.message_index < 0 or record.message_index >= len(messages):
            return f"[错误] 剪枝工具结果已失效: {prune_id}"
        message = messages[record.message_index]
        if message.get("role") != "tool" or str(message.get("tool_call_id", "")) != record.tool_call_id:
            return f"[错误] 剪枝工具结果已失效: {prune_id}"
        content = str(message.get("content", ""))
        if _hash_text(content) != record.content_hash:
            return f"[错误] 剪枝工具结果已失效: {prune_id}"
        safe_offset = max(0, int(offset or 0))
        safe_limit = max(1, min(int(limit or 8_000), max_chars))
        end = min(len(content), safe_offset + safe_limit)
        slice_text = content[safe_offset:end]
        has_more = end < len(content)
        payload = {
            "prune_id": prune_id,
            "tool_name": record.tool_name,
            "offset": safe_offset,
            "limit": safe_limit,
            "next_offset": end if has_more else None,
            "has_more": has_more,
            "content": slice_text,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _index_path(self) -> Path | None:
        return self.session_dir / "pruned_tool_results.json" if self.session_dir else None

    def _load_messages(self) -> list[dict[str, Any]]:
        if not self.session_dir:
            return []
        chat_file = self.session_dir / "chat.json"
        if not chat_file.exists():
            return []
        try:
            data = json.loads(chat_file.read_text(encoding="utf-8"))
        except Exception:
            return []
        return data if isinstance(data, list) else []

    def restored_events(self, keep_tokens: int) -> list[dict[str, Any]]:
        index = self.read_index()
        if not index.results:
            return []
        messages = self._load_messages()
        records = []
        for record in index.results.values():
            if record.message_index < 0 or record.message_index >= len(messages):
                continue
            message = messages[record.message_index]
            if message.get("role") != "tool" or str(message.get("tool_call_id", "")) != record.tool_call_id:
                continue
            content = str(message.get("content", ""))
            if _hash_text(content) != record.content_hash:
                continue
            retained_tokens = estimate_text_tokens(content[:max(1, keep_tokens * 4)])
            records.append({
                "stage": "completed",
                "reason": "restored_from_pruned_tool_results",
                "prune_id": record.prune_id,
                "tool_name": record.tool_name,
                "tool_call_id": record.tool_call_id,
                "original_tokens": record.original_estimated_tokens,
                "retained_tokens": min(retained_tokens, record.original_estimated_tokens),
                "omitted_tokens": max(0, record.original_estimated_tokens - retained_tokens),
                "message_index": record.message_index,
            })
        records.sort(key=lambda item: (int(item["message_index"]), str(item["prune_id"])))
        return records


class ToolResultPruner:
    def __init__(self, config: ToolResultPruningConfig):
        self.config = config

    def prune(
        self,
        messages: list[dict[str, Any]],
        session_dir: Path | None,
        context_trigger_tokens: int,
    ) -> ToolPruningResult:
        if not session_dir:
            return ToolPruningResult(messages=[dict(message) for message in messages], events=[], pruned=False)
        candidates = self._find_candidates(messages)
        selected = self._select_candidates(candidates, context_trigger_tokens)
        if not selected:
            return ToolPruningResult(messages=[dict(message) for message in messages], events=[], pruned=False)

        index = PrunedToolResultRepository(session_dir).read_index()
        index_results = dict(index.results)
        output = [dict(message) for message in messages]
        events: list[Event] = []
        now = datetime.now(timezone.utc).isoformat()

        for candidate, reason in selected:
            content_hash = _hash_text(candidate.content)
            prune_id = self._prune_id(candidate.tool_call_id, content_hash)
            existing = index_results.get(prune_id)
            index_results[prune_id] = PrunedToolResultRecord(
                prune_id=prune_id,
                message_index=candidate.message_index,
                tool_call_id=candidate.tool_call_id,
                tool_name=candidate.tool_name,
                content_hash=content_hash,
                original_estimated_tokens=candidate.tokens,
                created_at=existing.created_at if existing else now,
                updated_at=now,
            )
            preview = self._preview(candidate.content)
            retained_tokens = estimate_text_tokens(preview)
            omitted_tokens = max(0, candidate.tokens - retained_tokens)
            output[candidate.message_index]["content"] = self._marker(candidate, prune_id, preview, retained_tokens, omitted_tokens)
            events.append(Event.context_pruning(
                stage="completed",
                reason=reason,
                prune_id=prune_id,
                tool_name=candidate.tool_name,
                tool_call_id=candidate.tool_call_id,
                original_tokens=candidate.tokens,
                retained_tokens=retained_tokens,
                omitted_tokens=omitted_tokens,
                message_index=candidate.message_index,
            ))

        PrunedToolResultRepository(session_dir).write_index(PrunedToolResultIndex(version=1, results=index_results))
        return ToolPruningResult(messages=output, events=events, pruned=True)

    def apply_existing_index(self, messages: list[dict[str, Any]], session_dir: Path | None) -> ToolPruningResult:
        index = PrunedToolResultRepository(session_dir).read_index()
        if not index.results:
            return ToolPruningResult(messages=[dict(message) for message in messages], events=[], pruned=False)
        output = [dict(message) for message in messages]
        pruned = False
        for record in index.results.values():
            if record.message_index < 0 or record.message_index >= len(output):
                continue
            message = output[record.message_index]
            if message.get("role") != "tool" or str(message.get("tool_call_id", "")) != record.tool_call_id:
                continue
            content = str(message.get("content", ""))
            if _hash_text(content) != record.content_hash:
                continue
            preview = self._preview(content)
            retained_tokens = estimate_text_tokens(preview)
            omitted_tokens = max(0, record.original_estimated_tokens - retained_tokens)
            candidate = ToolResultCandidate(
                message_index=record.message_index,
                tool_call_id=record.tool_call_id,
                tool_name=record.tool_name,
                arguments="",
                content=content,
                tokens=record.original_estimated_tokens,
            )
            message["content"] = self._marker(candidate, record.prune_id, preview, retained_tokens, omitted_tokens)
            pruned = True
        return ToolPruningResult(messages=output, events=[], pruned=pruned)

    def _find_candidates(self, messages: list[dict[str, Any]]) -> list[ToolResultCandidate]:
        tool_calls_by_id: dict[str, tuple[str, str]] = {}
        for message in messages:
            if message.get("role") != "assistant":
                continue
            for tool_call in message.get("tool_calls") or []:
                function = tool_call.get("function") or {}
                tool_calls_by_id[str(tool_call.get("id", ""))] = (
                    str(function.get("name", "")),
                    str(function.get("arguments", "")),
                )

        candidates: list[ToolResultCandidate] = []
        for index, message in enumerate(messages):
            if message.get("role") != "tool":
                continue
            tool_call_id = str(message.get("tool_call_id", ""))
            tool_name, arguments = tool_calls_by_id.get(tool_call_id, ("", ""))
            if tool_name == "read_skill":
                continue
            content = str(message.get("content", ""))
            candidates.append(ToolResultCandidate(
                message_index=index,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
                content=content,
                tokens=estimate_text_tokens(content),
            ))
        return candidates

    def _select_candidates(self, candidates: list[ToolResultCandidate], context_trigger_tokens: int) -> list[tuple[ToolResultCandidate, str]]:
        selected: dict[int, tuple[ToolResultCandidate, str]] = {}
        for candidate in candidates:
            if candidate.tokens >= self.config.trigger_tokens:
                selected[candidate.message_index] = (candidate, "tool_result_exceeded_threshold")

        total_tool_tokens = sum(candidate.tokens for candidate in candidates)
        total_threshold = int(context_trigger_tokens * self.config.total_ratio)
        target_total = int(context_trigger_tokens * self.config.target_ratio)
        projected_total = total_tool_tokens - sum(item[0].tokens for item in selected.values())
        if total_threshold > 0 and total_tool_tokens >= total_threshold:
            for candidate in sorted(candidates, key=lambda item: item.tokens, reverse=True):
                if projected_total <= target_total:
                    break
                if candidate.message_index in selected:
                    continue
                selected[candidate.message_index] = (candidate, "tool_result_aggregate_pressure")
                projected_total -= candidate.tokens

        return list(selected.values())

    def _preview(self, content: str) -> str:
        if estimate_text_tokens(content) <= self.config.keep_tokens:
            return content
        limit = max(1, self.config.keep_tokens * 4)
        return content[:limit]

    def _marker(self, candidate: ToolResultCandidate, prune_id: str, preview: str, retained_tokens: int, omitted_tokens: int) -> str:
        return (
            "[MINICLAW_PRUNED_TOOL_RESULT]\n"
            f"prune_id: {prune_id}\n"
            f"tool_call_id: {candidate.tool_call_id}\n"
            f"tool_name: {candidate.tool_name}\n"
            f"original_tokens: {candidate.tokens}\n"
            f"retained_preview_tokens: {retained_tokens}\n"
            f"omitted_tokens: {omitted_tokens}\n\n"
            "Preview:\n"
            f"{preview}\n\n"
            "To inspect omitted content, call read_pruned_tool_result with:\n"
            f"{{\"prune_id\":\"{prune_id}\",\"offset\":0,\"limit\":8000}}\n"
            "[/MINICLAW_PRUNED_TOOL_RESULT]"
        )

    def _prune_id(self, tool_call_id: str, content_hash: str) -> str:
        payload = f"{tool_call_id}:{content_hash}"
        return "ptr_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def read_pruned_tool_result(
    prune_id: str,
    offset: int = 0,
    limit: int = 8_000,
    context: ToolExecutionContext | None = None,
) -> str:
    session_dir = context.session_dir if context else None
    max_chars = _positive_int_env("MINICLAW_PRUNED_TOOL_RESULT_READ_MAX_CHARS", 20_000)
    return PrunedToolResultRepository(session_dir).read_result(prune_id, offset=offset, limit=limit, max_chars=max_chars)


def get_pruned_tool_result_tools() -> list[Tool]:
    return [
        Tool(
            name="read_pruned_tool_result",
            description="Read omitted content from a MiniClaw [MINICLAW_PRUNED_TOOL_RESULT] marker in the current session. Use only when exact pruned tool output is needed.",
            parameters={
                "type": "object",
                "properties": {
                    "prune_id": {"type": "string", "description": "The prune_id shown in the pruned tool result marker."},
                    "offset": {"type": "integer", "description": "Character offset to start reading from. Default 0."},
                    "limit": {"type": "integer", "description": "Maximum characters to return. Default 8000; capped by backend config."},
                },
                "required": ["prune_id"],
            },
            handler=read_pruned_tool_result,
        )
    ]


def restored_pruning_records(session_dir: Path | None, keep_tokens: int = 2_000) -> list[dict[str, Any]]:
    return PrunedToolResultRepository(session_dir).restored_events(keep_tokens)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default
