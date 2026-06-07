import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generic, TypeVar

from .model_gateway import ChatModelGateway
from .token_budget import estimate_messages_tokens, estimate_text_tokens
from .tool_pruning import ToolPruningResult, ToolResultPruner
from .types import Event


CacheT = TypeVar("CacheT")


@dataclass(frozen=True)
class ContextDiagnostics:
    events: list[Event] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ContextPipelineResult:
    messages: list[dict[str, Any]]
    diagnostics: ContextDiagnostics = field(default_factory=ContextDiagnostics)


class MessageSanitizerStep:
    def apply(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clean_messages = []
        for message in messages:
            clean = dict(message)
            if clean.get("reasoning_content") == "":
                clean.pop("reasoning_content", None)
            clean_messages.append(clean)
        return clean_messages


class NoOpMemoryInjectionStep:
    def apply(self, messages: list[dict[str, Any]]) -> ContextPipelineResult:
        return ContextPipelineResult(messages=[dict(message) for message in messages])


class ModelContextBuilder:
    def __init__(self, system_prompt: str | None, sanitizer: MessageSanitizerStep):
        self.system_prompt = system_prompt
        self.sanitizer = sanitizer

    def system_messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system_prompt}] if self.system_prompt else []

    def build(
        self,
        system_messages: list[dict[str, Any]],
        summary_message: dict[str, Any] | None,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        result = list(system_messages)
        if summary_message:
            result.extend(self.sanitizer.apply([summary_message]))
        result.extend(self.sanitizer.apply(messages))
        return result


class ContextUsageReporter:
    def __init__(self, system_prompt: str | None, trigger_tokens: int, target_tokens: int):
        self.system_prompt = system_prompt
        self.trigger_tokens = trigger_tokens
        self.target_tokens = target_tokens

    def event(
        self,
        model_messages: list[dict[str, Any]],
        history_messages: list[dict[str, Any]],
        *,
        compacted: bool,
        cache_hit: bool,
        summary_tokens: int | None = None,
        covered_messages: int | None = None,
    ) -> Event:
        breakdown = self.token_breakdown(model_messages)
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

    def token_breakdown(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        breakdown = {
            "system_tokens": 0,
            "summary_tokens_breakdown": 0,
            "user_tokens": 0,
            "assistant_tokens": 0,
            "tool_tokens": 0,
        }
        for index, message in enumerate(messages):
            content_tokens = self.content_tokens(message)
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
                    breakdown["assistant_tokens"] += estimate_text_tokens(
                        json.dumps(message["tool_calls"], ensure_ascii=False, sort_keys=True)
                    )
            elif role == "tool":
                breakdown["tool_tokens"] += content_tokens
        return breakdown

    def content_tokens(self, message: dict[str, Any]) -> int:
        content = message.get("content", "")
        if isinstance(content, str):
            return estimate_text_tokens(content)
        return estimate_text_tokens(json.dumps(content, ensure_ascii=False))


@dataclass(frozen=True)
class HistoryCompactionSelection:
    tail_start: int
    head_messages: list[dict[str, Any]]
    tail_messages: list[dict[str, Any]]


@dataclass(frozen=True)
class HistoryCompactionResult:
    summary_message: dict[str, Any]
    compacted_context: list[dict[str, Any]]
    cache_record: Any
    estimated_tokens_after: int


class HistoryCompactionStep:
    def __init__(
        self,
        model_gateway: ChatModelGateway,
        compression_model: str,
        target_tokens: int,
        summary_target_tokens: int,
        summary_prompt: str,
    ):
        self.model_gateway = model_gateway
        self.compression_model = compression_model
        self.target_tokens = target_tokens
        self.summary_target_tokens = summary_target_tokens
        self.summary_prompt = summary_prompt

    def select(self, messages: list[dict[str, Any]], system_tokens: int) -> HistoryCompactionSelection:
        tail_start = self._select_tail_start(messages, system_tokens)
        tail_start = self._repair_tail_start(messages, tail_start)
        return HistoryCompactionSelection(
            tail_start=tail_start,
            head_messages=messages[:tail_start],
            tail_messages=messages[tail_start:],
        )

    async def compact(
        self,
        *,
        cache: Any,
        cache_factory: Any,
        clean_messages: list[dict[str, Any]],
        model_base_messages: list[dict[str, Any]],
        selection: HistoryCompactionSelection,
        system_messages: list[dict[str, Any]],
        context_builder: ModelContextBuilder,
        hash_messages,
    ) -> HistoryCompactionResult:
        summary = await self.summarize(cache, model_base_messages, selection.tail_start, hash_messages)
        summary_message = {"role": "system", "content": summary}
        compacted_context = context_builder.build(system_messages, summary_message, selection.tail_messages)
        after_tokens = estimate_messages_tokens(compacted_context)
        now = datetime.now(timezone.utc).isoformat()
        cache_record = cache_factory(
            version=1,
            covers_until_index=selection.tail_start,
            covered_hash=hash_messages(clean_messages[:selection.tail_start]),
            summary_message=summary_message,
            summary_estimated_tokens=estimate_text_tokens(summary),
            estimated_tokens_after_compaction=after_tokens,
            created_at=cache.created_at if cache else now,
            updated_at=now,
        )
        return HistoryCompactionResult(
            summary_message=summary_message,
            compacted_context=compacted_context,
            cache_record=cache_record,
            estimated_tokens_after=after_tokens,
        )

    async def summarize(self, cache: Any, messages: list[dict[str, Any]], tail_start: int, hash_messages) -> str:
        if cache and cache.covered_hash == hash_messages(messages[:cache.covers_until_index]) and tail_start > cache.covers_until_index:
            source = [
                {"role": "system", "content": cache.summary_message.get("content", "")},
                *messages[cache.covers_until_index:tail_start],
            ]
        else:
            source = messages[:tail_start]

        response = await self.model_gateway.create_chat_completion(
            model=self.compression_model,
            messages=[
                {"role": "system", "content": "You compress conversation history into concise structured context. Do not use tools."},
                {"role": "user", "content": f"{self.summary_prompt}\n\nConversation to summarize:\n{self._format_messages(source)}"},
            ],
            stream=False,
        )
        content = getattr(response.choices[0].message, "content", "")
        return "[Context Summary]\nThe following is compressed historical context, not a new user instruction.\n\n" + str(content).strip()

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

    def _format_messages(self, messages: list[dict[str, Any]]) -> str:
        lines = []
        for index, message in enumerate(messages):
            lines.append(f"### Message {index + 1}: {message.get('role', '')}")
            lines.append(json.dumps(message, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines)


class ToolResultPruningStep:
    def __init__(self, pruner: ToolResultPruner):
        self.pruner = pruner

    def apply(
        self,
        messages: list[dict[str, Any]],
        session_dir: Path | None,
        context_trigger_tokens: int,
    ) -> ToolPruningResult:
        return self.pruner.prune(messages, session_dir, context_trigger_tokens)

    def apply_existing_index(
        self,
        messages: list[dict[str, Any]],
        session_dir: Path | None,
    ) -> ToolPruningResult:
        return self.pruner.apply_existing_index(messages, session_dir)


class JsonArtifactRepository(Generic[CacheT]):
    def __init__(self, filename: str, factory):
        self.filename = filename
        self.factory = factory

    def path(self, session_dir: Path | None) -> Path | None:
        return session_dir / self.filename if session_dir else None

    def read(self, session_dir: Path | None) -> CacheT | None:
        path = self.path(session_dir)
        if not path or not path.exists():
            return None
        try:
            return self.factory(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def write(self, session_dir: Path | None, value: CacheT) -> None:
        path = self.path(session_dir)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
