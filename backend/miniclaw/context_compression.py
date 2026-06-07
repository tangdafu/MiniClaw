import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .context_pipeline import (
    ContextUsageReporter,
    HistoryCompactionStep,
    JsonArtifactRepository,
    MessageSanitizerStep,
    ModelContextBuilder,
    NoOpMemoryInjectionStep,
    ToolResultPruningStep,
)
from .model_gateway import ChatModelGateway, OpenAIChatModelGateway
from .token_budget import estimate_messages_tokens
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
        model_gateway: ChatModelGateway | None = None,
    ):
        self.client = client
        self.model_gateway = model_gateway or OpenAIChatModelGateway(client)
        self.model = model
        self.system_prompt = system_prompt
        self.trigger_tokens = trigger_tokens
        self.target_tokens = target_tokens
        self.summary_target_tokens = summary_target_tokens
        self.compression_model = compression_model or model
        self.tool_pruner = ToolResultPruner(tool_result_pruning or ToolResultPruningConfig())
        self.message_sanitizer = MessageSanitizerStep()
        self.memory_injector = NoOpMemoryInjectionStep()
        self.tool_pruning_step = ToolResultPruningStep(self.tool_pruner)
        self.cache_repository = JsonArtifactRepository("model_context.json", ModelContextCache.from_dict)
        self.context_builder = ModelContextBuilder(self.system_prompt, self.message_sanitizer)
        self.usage_reporter = ContextUsageReporter(self.system_prompt, self.trigger_tokens, self.target_tokens)
        self.history_compactor = HistoryCompactionStep(
            model_gateway=self.model_gateway,
            compression_model=self.compression_model,
            target_tokens=self.target_tokens,
            summary_target_tokens=self.summary_target_tokens,
            summary_prompt=CONTEXT_SUMMARY_PROMPT,
        )

    async def prepare(
        self,
        messages: list[dict[str, Any]],
        session_dir: Path | None = None,
    ) -> AsyncIterator[Event | PreparedContext]:
        clean_messages = self.message_sanitizer.apply(messages)
        memory_result = self.memory_injector.apply(clean_messages)
        clean_messages = memory_result.messages
        pruning_result = self.tool_pruning_step.apply(clean_messages, session_dir, self.trigger_tokens)
        for event in pruning_result.events:
            yield event
        model_base_messages = pruning_result.messages
        system_messages = self.context_builder.system_messages()
        cache = self.cache_repository.read(session_dir)

        if cache and self._cache_hash_matches(cache, clean_messages):
            cached_context = self.context_builder.build(system_messages, cache.summary_message, model_base_messages[cache.covers_until_index:])
            cached_tokens = estimate_messages_tokens(cached_context)
            if cached_tokens <= self.trigger_tokens:
                yield self.usage_reporter.event(
                    cached_context,
                    clean_messages,
                    compacted=True,
                    cache_hit=True,
                    summary_tokens=cache.summary_estimated_tokens,
                    covered_messages=cache.covers_until_index,
                )
                yield PreparedContext(cached_context)
                return

        full_context = self.context_builder.build(system_messages, None, model_base_messages)
        full_tokens = estimate_messages_tokens(full_context)
        if not cache and full_tokens <= self.trigger_tokens:
            yield self.usage_reporter.event(
                full_context,
                clean_messages,
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

        selection = self.history_compactor.select(model_base_messages, estimate_messages_tokens(system_messages))
        yield Event.context_compression(
            stage="selected_range",
            reason="context_tokens_exceeded",
            head_messages=len(selection.head_messages),
            tail_messages=len(selection.tail_messages),
        )

        if not selection.head_messages:
            yield Event.context_compression(
                stage="failed",
                reason="single_message_too_large",
                detail="Context exceeds the target but no older message range can be summarized without splitting messages.",
            )
            yield PreparedContext(full_context)
            return

        yield Event.context_compression(stage="summarizing", reason="context_tokens_exceeded")
        compaction = await self.history_compactor.compact(
            cache=cache,
            cache_factory=ModelContextCache,
            clean_messages=clean_messages,
            model_base_messages=model_base_messages,
            selection=selection,
            system_messages=system_messages,
            context_builder=self.context_builder,
            hash_messages=self._hash_messages,
        )
        self.cache_repository.write(session_dir, compaction.cache_record)
        yield Event.context_compression(
            stage="completed",
            reason="context_tokens_exceeded",
            covered_messages=selection.tail_start,
            summary_tokens=compaction.cache_record.summary_estimated_tokens,
            estimated_tokens_after=compaction.estimated_tokens_after,
        )
        yield self.usage_reporter.event(
            compaction.compacted_context,
            clean_messages,
            compacted=True,
            cache_hit=False,
            summary_tokens=compaction.cache_record.summary_estimated_tokens,
            covered_messages=selection.tail_start,
        )
        yield PreparedContext(compaction.compacted_context)

    def usage_for_saved_messages(
        self,
        messages: list[dict[str, Any]],
        session_dir: Path | None = None,
    ) -> Event:
        clean_messages = self.message_sanitizer.apply(messages)
        memory_result = self.memory_injector.apply(clean_messages)
        clean_messages = memory_result.messages
        pruning_result = self.tool_pruning_step.apply_existing_index(clean_messages, session_dir)
        model_base_messages = pruning_result.messages
        system_messages = self.context_builder.system_messages()
        cache = self.cache_repository.read(session_dir)

        if cache and self._cache_hash_matches(cache, clean_messages):
            cached_context = self.context_builder.build(system_messages, cache.summary_message, model_base_messages[cache.covers_until_index:])
            cached_tokens = estimate_messages_tokens(cached_context)
            if cached_tokens <= self.trigger_tokens:
                return self.usage_reporter.event(
                    cached_context,
                    clean_messages,
                    compacted=True,
                    cache_hit=True,
                    summary_tokens=cache.summary_estimated_tokens,
                    covered_messages=cache.covers_until_index,
                )

        full_context = self.context_builder.build(system_messages, None, model_base_messages)
        return self.usage_reporter.event(
            full_context,
            clean_messages,
            compacted=False,
            cache_hit=False,
        )

    def _cache_hash_matches(self, cache: ModelContextCache, messages: list[dict[str, Any]]) -> bool:
        return cache.covered_hash == self._hash_messages(messages[:cache.covers_until_index])

    def _hash_messages(self, messages: list[dict[str, Any]]) -> str:
        payload = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
