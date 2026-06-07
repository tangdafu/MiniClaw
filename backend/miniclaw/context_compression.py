import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .token_budget import estimate_messages_tokens, estimate_text_tokens
from .tool_pruning import ToolResultPruner, ToolResultPruningConfig
from .types import Event


CONTEXT_SUMMARY_PROMPT = """Provide a structured context summary for continuing this conversation.
Focus on information that will help the assistant continue accurately. Do not invent facts.

Use this format:

## Goal
[What goal(s) is the user trying to accomplish?]

## Instructions
[Important user instructions, preferences, constraints, or decisions]

## Discoveries
[Important facts discovered through discussion or tools]

## Accomplished
[What has been completed and what remains in progress]

## Relevant files / directories
[Important files, directories, commands, tools, and outputs referenced]
"""


@dataclass(frozen=True)
class PreparedContext:
    messages: list[dict[str, Any]]


@dataclass(frozen=True)
class ModelContextCache:
    version: int
    covers_until_index: int
    covered_hash: str
    summary_message: dict[str, Any]
    summary_estimated_tokens: int
    estimated_tokens_after_compaction: int
    created_at: str
    updated_at: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelContextCache":
        return cls(
            version=int(data.get("version", 1)),
            covers_until_index=int(data.get("covers_until_index", 0)),
            covered_hash=str(data.get("covered_hash", "")),
            summary_message=dict(data.get("summary_message") or {}),
            summary_estimated_tokens=int(data.get("summary_estimated_tokens", 0)),
            estimated_tokens_after_compaction=int(data.get("estimated_tokens_after_compaction", 0)),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "covers_until_index": self.covers_until_index,
            "covered_hash": self.covered_hash,
            "summary_message": self.summary_message,
            "summary_estimated_tokens": self.summary_estimated_tokens,
            "estimated_tokens_after_compaction": self.estimated_tokens_after_compaction,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ContextCompressionService:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        system_prompt: str | None,
        trigger_tokens: int,
        target_tokens: int,
        summary_target_tokens: int,
        compression_model: str | None = None,
        tool_result_pruning: ToolResultPruningConfig | None = None,
    ):
        self.client = client
        self.model = model
        self.system_prompt = system_prompt
        self.trigger_tokens = trigger_tokens
        self.target_tokens = target_tokens
        self.summary_target_tokens = summary_target_tokens
        self.compression_model = compression_model or model
        self.tool_pruner = ToolResultPruner(tool_result_pruning or ToolResultPruningConfig())

    async def prepare(
        self,
        messages: list[dict[str, Any]],
        session_dir: Path | None = None,
    ) -> AsyncIterator[Event | PreparedContext]:
        clean_messages = [self._clean_message(message) for message in messages]
        pruning_result = self.tool_pruner.prune(clean_messages, session_dir, self.trigger_tokens)
        for event in pruning_result.events:
            yield event
        model_base_messages = pruning_result.messages
        system_messages = self._system_messages()
        cache = self._read_cache(session_dir)

        if cache and self._cache_hash_matches(cache, clean_messages):
            cached_context = self._build_context(system_messages, cache.summary_message, model_base_messages[cache.covers_until_index:])
            cached_tokens = estimate_messages_tokens(cached_context)
            if cached_tokens <= self.trigger_tokens:
                yield self._usage_event(
                    cached_context,
                    clean_messages,
                    estimated_tokens=cached_tokens,
                    compacted=True,
                    cache_hit=True,
                    summary_tokens=cache.summary_estimated_tokens,
                    covered_messages=cache.covers_until_index,
                )
                yield PreparedContext(cached_context)
                return

        full_context = self._build_context(system_messages, None, model_base_messages)
        full_tokens = estimate_messages_tokens(full_context)
        if not cache and full_tokens <= self.trigger_tokens:
            yield self._usage_event(
                full_context,
                clean_messages,
                estimated_tokens=full_tokens,
                compacted=False,
                cache_hit=False,
            )
            yield PreparedContext(full_context)
            return

        yield Event.context_compression(
            stage="started",
            reason="context_tokens_exceeded",
            estimated_tokens=full_tokens,
            trigger_tokens=self.trigger_tokens,
            target_tokens=self.target_tokens,
        )

        tail_start = self._select_tail_start(model_base_messages, estimate_messages_tokens(system_messages))
        tail_start = self._repair_tail_start(model_base_messages, tail_start)
        head_messages = model_base_messages[:tail_start]
        tail_messages = model_base_messages[tail_start:]
        yield Event.context_compression(
            stage="selected_range",
            reason="context_tokens_exceeded",
            head_messages=len(head_messages),
            tail_messages=len(tail_messages),
        )

        if not head_messages:
            yield Event.context_compression(
                stage="failed",
                reason="single_message_too_large",
                detail="Context exceeds the target but no older message range can be summarized without splitting messages.",
            )
            yield PreparedContext(full_context)
            return

        yield Event.context_compression(stage="summarizing", reason="context_tokens_exceeded")
        summary = await self._summarize(cache, model_base_messages, tail_start)
        summary_message = {"role": "system", "content": summary}
        compacted_context = self._build_context(system_messages, summary_message, tail_messages)
        after_tokens = estimate_messages_tokens(compacted_context)
        now = datetime.now(timezone.utc).isoformat()
        cache_to_write = ModelContextCache(
            version=1,
            covers_until_index=tail_start,
            covered_hash=self._hash_messages(clean_messages[:tail_start]),
            summary_message=summary_message,
            summary_estimated_tokens=estimate_text_tokens(summary),
            estimated_tokens_after_compaction=after_tokens,
            created_at=cache.created_at if cache else now,
            updated_at=now,
        )
        self._write_cache(session_dir, cache_to_write)
        yield Event.context_compression(
            stage="completed",
            reason="context_tokens_exceeded",
            covered_messages=tail_start,
            summary_tokens=cache_to_write.summary_estimated_tokens,
            estimated_tokens_after=after_tokens,
        )
        yield self._usage_event(
            compacted_context,
            clean_messages,
            estimated_tokens=after_tokens,
            compacted=True,
            cache_hit=False,
            summary_tokens=cache_to_write.summary_estimated_tokens,
            covered_messages=tail_start,
        )
        yield PreparedContext(compacted_context)

    def usage_for_saved_messages(
        self,
        messages: list[dict[str, Any]],
        session_dir: Path | None = None,
    ) -> Event:
        clean_messages = [self._clean_message(message) for message in messages]
        pruning_result = self.tool_pruner.apply_existing_index(clean_messages, session_dir)
        model_base_messages = pruning_result.messages
        system_messages = self._system_messages()
        cache = self._read_cache(session_dir)

        if cache and self._cache_hash_matches(cache, clean_messages):
            cached_context = self._build_context(system_messages, cache.summary_message, model_base_messages[cache.covers_until_index:])
            cached_tokens = estimate_messages_tokens(cached_context)
            if cached_tokens <= self.trigger_tokens:
                return self._usage_event(
                    cached_context,
                    clean_messages,
                    estimated_tokens=cached_tokens,
                    compacted=True,
                    cache_hit=True,
                    summary_tokens=cache.summary_estimated_tokens,
                    covered_messages=cache.covers_until_index,
                )

        full_context = self._build_context(system_messages, None, model_base_messages)
        return self._usage_event(
            full_context,
            clean_messages,
            estimated_tokens=estimate_messages_tokens(full_context),
            compacted=False,
            cache_hit=False,
        )

    def _system_messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system_prompt}] if self.system_prompt else []

    def _build_context(
        self,
        system_messages: list[dict[str, Any]],
        summary_message: dict[str, Any] | None,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = list(system_messages)
        if summary_message:
            result.append(self._clean_message(summary_message))
        result.extend(self._clean_message(message) for message in messages)
        return result

    def _usage_event(
        self,
        model_messages: list[dict[str, Any]],
        history_messages: list[dict[str, Any]],
        *,
        estimated_tokens: int,
        compacted: bool,
        cache_hit: bool,
        summary_tokens: int | None = None,
        covered_messages: int | None = None,
    ) -> Event:
        breakdown = self._token_breakdown(model_messages)
        display_tokens = sum(breakdown.values())
        return Event.context_usage(
            stage="prepared",
            reason="summary_cache" if cache_hit else "token_budget",
            estimated_tokens=display_tokens,
            trigger_tokens=self.trigger_tokens,
            target_tokens=self.target_tokens,
            model_messages=len(model_messages),
            history_messages=len(history_messages),
            compacted=compacted,
            cache_hit=cache_hit,
            summary_tokens=summary_tokens,
            covered_messages=covered_messages,
            **breakdown,
        )

    def _token_breakdown(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        breakdown = {
            "system_tokens": 0,
            "summary_tokens_breakdown": 0,
            "user_tokens": 0,
            "assistant_tokens": 0,
            "tool_tokens": 0,
        }
        for index, message in enumerate(messages):
            content_tokens = self._content_tokens(message)
            role = message.get("role")
            if role == "system" and index == 0 and self.system_prompt:
                breakdown["system_tokens"] += content_tokens
            elif role == "system" and str(message.get("content", "")).startswith("[Context Summary]"):
                breakdown["summary_tokens_breakdown"] += content_tokens
            elif role == "user":
                breakdown["user_tokens"] += content_tokens
            elif role == "assistant":
                breakdown["assistant_tokens"] += content_tokens
                if message.get("tool_calls"):
                    breakdown["assistant_tokens"] += estimate_text_tokens(json.dumps(message["tool_calls"], ensure_ascii=False, sort_keys=True))
            elif role == "tool":
                breakdown["tool_tokens"] += content_tokens
        return breakdown

    def _content_tokens(self, message: dict[str, Any]) -> int:
        content = message.get("content", "")
        if isinstance(content, str):
            return estimate_text_tokens(content)
        return estimate_text_tokens(json.dumps(content, ensure_ascii=False))

    def _select_tail_start(self, messages: list[dict[str, Any]], system_tokens: int) -> int:
        tail_budget = max(1_000, self.target_tokens - self.summary_target_tokens - system_tokens)
        total = 0
        start = len(messages)
        for index in range(len(messages) - 1, -1, -1):
            message_tokens = estimate_messages_tokens([messages[index]])
            if start < len(messages) and total + message_tokens > tail_budget:
                break
            total += message_tokens
            start = index
        return start

    def _repair_tail_start(self, messages: list[dict[str, Any]], start: int) -> int:
        if start <= 0 or start >= len(messages) or messages[start].get("role") != "tool":
            return start
        leading_tool_ids = []
        for message in messages[start:]:
            if message.get("role") != "tool":
                break
            if message.get("tool_call_id"):
                leading_tool_ids.append(message["tool_call_id"])
        for index in range(start - 1, -1, -1):
            message = messages[index]
            if message.get("role") != "assistant":
                continue
            assistant_tool_ids = {
                tool_call.get("id")
                for tool_call in message.get("tool_calls", [])
                if tool_call.get("id")
            }
            if set(leading_tool_ids).issubset(assistant_tool_ids):
                return index
        return start

    async def _summarize(self, cache: ModelContextCache | None, messages: list[dict[str, Any]], tail_start: int) -> str:
        if cache and self._cache_hash_matches(cache, messages) and tail_start > cache.covers_until_index:
            source = [
                {"role": "system", "content": cache.summary_message.get("content", "")},
                *messages[cache.covers_until_index:tail_start],
            ]
        else:
            source = messages[:tail_start]

        response = await self.client.chat.completions.create(
            model=self.compression_model,
            messages=[
                {"role": "system", "content": "You compress conversation history into concise structured context. Do not use tools."},
                {"role": "user", "content": f"{CONTEXT_SUMMARY_PROMPT}\n\nConversation to summarize:\n{self._format_messages(source)}"},
            ],
            stream=False,
        )
        content = getattr(response.choices[0].message, "content", "")
        return "[Context Summary]\nThe following is compressed historical context, not a new user instruction.\n\n" + str(content).strip()

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        lines = []
        for index, message in enumerate(messages):
            lines.append(f"### Message {index + 1}: {message.get('role', '')}")
            lines.append(json.dumps(message, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines)

    def _clean_message(self, message: dict[str, Any]) -> dict[str, Any]:
        clean = dict(message)
        if clean.get("reasoning_content") == "":
            clean.pop("reasoning_content", None)
        return clean

    def _cache_path(self, session_dir: Path | None) -> Path | None:
        return session_dir / "model_context.json" if session_dir else None

    def _read_cache(self, session_dir: Path | None) -> ModelContextCache | None:
        path = self._cache_path(session_dir)
        if not path or not path.exists():
            return None
        try:
            return ModelContextCache.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def _write_cache(self, session_dir: Path | None, cache: ModelContextCache) -> None:
        path = self._cache_path(session_dir)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _cache_hash_matches(self, cache: ModelContextCache, messages: list[dict[str, Any]]) -> bool:
        return cache.covered_hash == self._hash_messages(messages[:cache.covers_until_index])

    def _hash_messages(self, messages: list[dict[str, Any]]) -> str:
        payload = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
