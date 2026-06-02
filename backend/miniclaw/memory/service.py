import json
from datetime import datetime, timezone

from .config import MemoryConfig
from .embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from .index import SQLiteMemoryIndex
from .models import MemoryRecord, MemorySearchResult
from .store import MarkdownMemoryStore
from .text import chunk_text, normalize_search_text


class MemoryService:
    def __init__(
        self,
        config: MemoryConfig | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ):
        self.config = config or MemoryConfig.from_env()
        self.store = MarkdownMemoryStore(self.config.memory_dir)
        self.index = SQLiteMemoryIndex(self.config.sqlite_path)
        self.embedding_provider = embedding_provider or OpenAIEmbeddingProvider(self.config)

    async def remember(
        self,
        title: str,
        content: str,
        memory_type: str = "memory",
        topic: str | None = None,
        memory_date: str | None = None,
        tags: list[str] | None = None,
        source: str = "user_explicit",
        confidence: float = 0.9,
    ) -> MemoryRecord:
        record, _markdown = self.store.create(
            title=title,
            content=content,
            memory_type=memory_type,
            topic=topic,
            memory_date=memory_date,
            tags=tags,
            source=source,
            confidence=confidence,
        )
        body = self.store.body_from_markdown(self.store.read_by_path(record.path))
        if self.index.memory_content_hash(record.id) == record.content_hash:
            return record
        chunks = chunk_text(record.id, body, self.config.chunk_size, self.config.chunk_overlap)
        embeddings = await self._embed_chunks(chunks)
        self.index.index_memory(record, chunks, embeddings=embeddings)
        return record

    async def reindex_all_memories(self) -> dict[str, object]:
        self.index.clear_active_index()
        indexed = 0
        skipped = 0
        errors: list[dict[str, str]] = []

        for path in self.store.iter_memory_files():
            relative_path = path.relative_to(self.config.memory_dir).as_posix()
            try:
                markdown = path.read_text(encoding="utf-8")
                record = self.store.record_from_markdown(relative_path, markdown)
                body = self.store.body_from_markdown(markdown)
                chunks = chunk_text(record.id, body, self.config.chunk_size, self.config.chunk_overlap)
                embeddings = await self._embed_chunks(chunks)
                self.index.index_memory(record, chunks, embeddings=embeddings)
                indexed += 1
            except Exception as exc:
                skipped += 1
                errors.append({"path": relative_path, "error": str(exc)})

        return {"indexed": indexed, "skipped": skipped, "errors": errors}

    async def search(
        self,
        query: str,
        mode: str = "hybrid",
        memory_type: str | None = None,
        limit: int = 5,
    ) -> tuple[list[MemorySearchResult], str | None]:
        safe_limit = self._safe_limit(limit)
        normalized_mode = (mode or "hybrid").lower()
        if not normalize_search_text(query):
            return [], "empty search query"

        if normalized_mode == "fts":
            results, warning = self.index.search_fts(query, limit=safe_limit * 2, memory_type=memory_type)
            return self._dedupe_by_memory(results, safe_limit), warning

        if normalized_mode == "vector":
            if not self.embedding_provider.available:
                return [], "vector search unavailable: embeddings are not configured"
            query_vector = await self.embedding_provider.embed(query)
            results = self.index.search_vector(query_vector, self.embedding_provider.model, safe_limit * 2, memory_type)
            return self._dedupe_by_memory(results, safe_limit), None

        if normalized_mode == "hybrid":
            fts_results, _ = self.index.search_fts(query, limit=safe_limit * 2, memory_type=memory_type)
            if not self.embedding_provider.available:
                return self._dedupe_by_memory(fts_results, safe_limit), "vector search unavailable; returned FTS results"
            query_vector = await self.embedding_provider.embed(query)
            vector_results = self.index.search_vector(query_vector, self.embedding_provider.model, safe_limit * 2, memory_type)
            return self._dedupe_by_memory(self._merge_results(fts_results, vector_results, safe_limit * 2), safe_limit), None

        return [], f"unknown search mode: {mode}"

    def read_memory(self, memory_id: str) -> str:
        record = self.index.get_memory(memory_id)
        if not record:
            return f"[错误] 记忆不存在: {memory_id}"
        try:
            return self.store.read_by_path(record.path)
        except FileNotFoundError:
            return f"[错误] 记忆文件不存在: {memory_id}"

    def forget_memory(self, memory_id: str) -> str:
        record = self.index.get_memory(memory_id)
        if not record:
            return f"[错误] 记忆不存在: {memory_id}"
        trash_path = self.store.forget(record.path, memory_id)
        deleted_at = datetime.now(timezone.utc).isoformat()
        self.index.forget_memory(memory_id, deleted_at, trash_path=trash_path)
        return f"已删除记忆: {memory_id}"

    async def _embed_chunks(self, chunks) -> dict[str, tuple[str, list[float]]] | None:
        if not self.embedding_provider.available:
            return None
        embeddings: dict[str, tuple[str, list[float]]] = {}
        try:
            for chunk in chunks:
                embeddings[chunk.id] = (self.embedding_provider.model, await self.embedding_provider.embed(chunk.content))
        except Exception:
            return None
        return embeddings

    def _merge_results(
        self,
        fts_results: list[MemorySearchResult],
        vector_results: list[MemorySearchResult],
        limit: int,
    ) -> list[MemorySearchResult]:
        merged: dict[str, MemorySearchResult] = {}
        scores: dict[str, float] = {}

        for result in fts_results:
            merged[result.chunk_id] = result
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + result.score * 0.4

        for result in vector_results:
            merged.setdefault(result.chunk_id, result)
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + result.score * 0.6

        ranked = []
        for chunk_id, result in merged.items():
            ranked.append(
                MemorySearchResult(
                    memory_id=result.memory_id,
                    chunk_id=result.chunk_id,
                    path=result.path,
                    title=result.title,
                    type=result.type,
                    tags=result.tags,
                    score=scores[chunk_id],
                    match_type="hybrid",
                    excerpt=result.excerpt,
                    chunk_index=result.chunk_index,
                    start_char=result.start_char,
                    end_char=result.end_char,
                )
            )
        ranked.sort(key=lambda result: result.score, reverse=True)
        return ranked[:limit]

    def _dedupe_by_memory(self, results: list[MemorySearchResult], limit: int) -> list[MemorySearchResult]:
        selected: list[MemorySearchResult] = []
        seen: set[str] = set()
        for result in results:
            if result.memory_id in seen:
                continue
            selected.append(result)
            seen.add(result.memory_id)
            if len(selected) >= limit:
                break
        return selected

    def format_record(self, record: MemoryRecord) -> str:
        return json.dumps({
            "memory_id": record.id,
            "path": record.path,
            "title": record.title,
            "type": record.type,
            "tags": record.tags,
            "read_hint": f"Use read_memory('{record.id}') to read the full Markdown document.",
        }, ensure_ascii=False, indent=2)

    def format_search_results(self, results: list[MemorySearchResult], warning: str | None = None) -> str:
        payload = {
            "warning": warning,
            "results": [
                {
                    "memory_id": result.memory_id,
                    "chunk_id": result.chunk_id,
                    "path": result.path,
                    "title": result.title,
                    "type": result.type,
                    "document_scope": result.type,
                    "tags": result.tags,
                    "score": round(result.score, 6),
                    "match_type": result.match_type,
                    "chunk_index": result.chunk_index,
                    "start_char": result.start_char,
                    "end_char": result.end_char,
                    "excerpt": result.excerpt,
                    "read_hint": f"Use read_memory('{result.memory_id}') to read the full Markdown document.",
                }
                for result in results
            ],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def format_reindex_result(self, result: dict[str, object]) -> str:
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _safe_limit(self, limit: int) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError):
            return 5
        return min(max(value, 1), 20)
