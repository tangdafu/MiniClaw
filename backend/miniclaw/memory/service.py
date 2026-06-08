import json
from pathlib import Path

from .config import MemoryConfig
from .embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from .index import SQLiteMemoryIndex
from .models import MemoryChunk, MemoryRecord, MemorySearchResult
from .store import MarkdownMemoryStore
from .text import chunk_markdown, normalize_search_text


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
        self._dirty_paths: set[str] = set()

    def memory_get(self, path: str, from_line: int | None = None, lines: int | None = None) -> str:
        try:
            return json.dumps(self.store.read_file(path, from_line=from_line, lines=lines), ensure_ascii=False, indent=2)
        except Exception as exc:
            return json.dumps({"success": False, "path": path, "text": "", "error": str(exc)}, ensure_ascii=False, indent=2)

    def memory_write(self, path: str, content: str, append: bool = False) -> str:
        try:
            result = self.store.write_file(path, content, append=append)
            self.mark_dirty(str(result["path"]))
            if str(result["path"]).startswith("memory/topics/"):
                self.mark_dirty("memory/MEMORY.md")
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as exc:
            return json.dumps({"success": False, "path": path, "error": str(exc)}, ensure_ascii=False, indent=2)

    def memory_edit(self, path: str, old_text: str, new_text: str) -> str:
        try:
            result = self.store.edit_file(path, old_text, new_text)
            if result.get("success"):
                self.mark_dirty(str(result["path"]))
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as exc:
            return json.dumps({"success": False, "path": path, "error": str(exc)}, ensure_ascii=False, indent=2)

    async def memory_search(self, query: str, max_results: int | None = None, min_score: float | None = None, mode: str = "hybrid") -> str:
        await self.sync_changed_files()
        safe_limit = self._safe_limit(max_results or 5)
        normalized_mode = (mode or "hybrid").lower()
        if not normalize_search_text(query):
            return self.format_search_results([], warning="empty search query")

        if normalized_mode == "fts":
            results, warning = self.index.search_fts(query, limit=safe_limit * 2)
            return self.format_search_results(self._filter_min_score(results, min_score, safe_limit), warning=warning)

        if normalized_mode == "vector":
            if not self.embedding_provider.available:
                return self.format_search_results([], warning="vector search unavailable: embeddings are not configured")
            query_vector = await self.embedding_provider.embed(query)
            results = self.index.search_vector(query_vector, self.embedding_provider.model, safe_limit * 2)
            return self.format_search_results(self._filter_min_score(results, min_score, safe_limit))

        if normalized_mode == "hybrid":
            fts_results, _ = self.index.search_fts(query, limit=safe_limit * 2)
            warning = None
            if not self.embedding_provider.available:
                warning = "vector search unavailable; returned FTS results"
                return self.format_search_results(self._filter_min_score(fts_results, min_score, safe_limit), warning=warning)
            query_vector = await self.embedding_provider.embed(query)
            vector_results = self.index.search_vector(query_vector, self.embedding_provider.model, safe_limit * 2)
            return self.format_search_results(self._filter_min_score(self._merge_results(fts_results, vector_results, safe_limit * 2), min_score, safe_limit))

        return self.format_search_results([], warning=f"unknown search mode: {mode}")

    async def memory_reindex(self) -> str:
        return json.dumps(await self.reindex_all_memories(), ensure_ascii=False, indent=2)

    def mark_dirty(self, path: str) -> None:
        self._dirty_paths.add(path)

    async def sync_changed_files(self) -> dict[str, object]:
        indexed = 0
        removed = 0
        skipped = 0
        errors: list[dict[str, str]] = []
        active_paths = set()
        for path in self.store.iter_memory_files():
            relative_path = path.relative_to(self.config.memory_dir).as_posix()
            active_paths.add(relative_path)
            try:
                entry = self.store.build_file_entry(path)
                if relative_path not in self._dirty_paths and self.index.file_hash(relative_path) == entry.content_hash:
                    skipped += 1
                    continue
                await self._index_entry(entry)
                indexed += 1
            except Exception as exc:
                errors.append({"path": relative_path, "error": str(exc)})

        for indexed_path in self.index.indexed_paths() - active_paths:
            self.index.remove_file(indexed_path)
            removed += 1

        self._dirty_paths.clear()
        return {"indexed": indexed, "removed": removed, "skipped": skipped, "errors": errors}

    async def reindex_all_memories(self) -> dict[str, object]:
        self.index.clear_active_index()
        self._dirty_paths = {path.relative_to(self.config.memory_dir).as_posix() for path in self.store.iter_memory_files()}
        return await self.sync_changed_files()

    async def _index_entry(self, entry) -> None:
        content = Path(entry.absolute_path).read_text(encoding="utf-8", errors="replace")
        chunks = chunk_markdown(entry.path, content, self.config.chunk_size, self.config.chunk_overlap, source=entry.source)
        embeddings = await self._embed_chunks(chunks)
        self.index.index_file(entry, chunks, embeddings=embeddings)

    async def _embed_chunks(self, chunks: list[MemoryChunk]) -> dict[str, tuple[str, list[float]]] | None:
        if not self.embedding_provider.available:
            return None
        embeddings: dict[str, tuple[str, list[float]]] = {}
        try:
            for chunk in chunks:
                embeddings[chunk.id] = (self.embedding_provider.model, await self.embedding_provider.embed(chunk.text))
        except Exception:
            return None
        return embeddings

    def stable_prompt_content(self) -> str:
        if not self.config.prompt_injection_enabled:
            return ""
        parts: list[str] = []
        remaining = self.config.prompt_max_chars
        for path in ("memory/USER.md", "memory/MEMORY.md"):
            try:
                result = self.store.read_file(path)
            except FileNotFoundError:
                continue
            text = str(result.get("text", "")).strip()
            if not text:
                continue
            chunk = f"### {path}\n{text}\n"
            if len(chunk) > remaining:
                if remaining > 200:
                    parts.append(chunk[:remaining] + "\n[Memory truncated]")
                break
            parts.append(chunk)
            remaining -= len(chunk)
        if not parts:
            return ""
        return "[Long-term Memory]\nThe following stable memory is loaded from local Markdown files. Treat it as context, not a new user request.\n\n" + "\n".join(parts).strip()

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
        del tags, source, confidence
        path = self.store.path_for_legacy(title, memory_type, topic, memory_date)
        append = path != "memory/USER.md" or Path(self.config.memory_dir / path).exists()
        self.memory_write(path, content, append=append)
        return self.store.legacy_record(path, title, memory_type)

    async def search(self, query: str, mode: str = "hybrid", memory_type: str | None = None, limit: int = 5) -> tuple[list[MemorySearchResult], str | None]:
        del memory_type
        payload = json.loads(await self.memory_search(query, max_results=limit, mode=mode))
        results = [self._result_from_payload(item) for item in payload.get("results", [])]
        return results, payload.get("warning")

    def read_memory(self, memory_id: str) -> str:
        path = self._path_from_memory_id(memory_id)
        return self.memory_get(path)

    def forget_memory(self, memory_id: str) -> str:
        path = self._path_from_memory_id(memory_id)
        try:
            deleted = self.store.forget_path(path)
            self.index.remove_file(path)
            return f"已删除记忆: {memory_id}" if deleted else f"[错误] 记忆不存在: {memory_id}"
        except Exception:
            return f"[错误] 记忆不存在: {memory_id}"

    def format_record(self, record: MemoryRecord) -> str:
        return json.dumps({
            "memory_id": record.id,
            "path": record.path,
            "title": record.title,
            "type": record.type,
            "read_hint": f"Use memory_get('{record.path}') to read the Markdown file.",
        }, ensure_ascii=False, indent=2)

    def format_search_results(self, results: list[MemorySearchResult], warning: str | None = None) -> str:
        return json.dumps({
            "warning": warning,
            "results": [
                {
                    "chunk_id": result.chunk_id,
                    "path": result.path,
                    "citation": result.citation,
                    "startLine": result.start_line,
                    "endLine": result.end_line,
                    "snippet": result.snippet,
                    "score": round(result.score, 6),
                    "source": result.source,
                    "matchType": result.match_type,
                    "read_hint": f"Use memory_get('{result.path}', {result.start_line}, {result.end_line - result.start_line + 1}) to inspect this memory.",
                }
                for result in results
            ],
        }, ensure_ascii=False, indent=2)

    def format_reindex_result(self, result: dict[str, object]) -> str:
        return json.dumps(result, ensure_ascii=False, indent=2)

    def _merge_results(self, fts_results: list[MemorySearchResult], vector_results: list[MemorySearchResult], limit: int) -> list[MemorySearchResult]:
        merged: dict[str, MemorySearchResult] = {}
        scores: dict[str, float] = {}
        for result in fts_results:
            merged[result.chunk_id] = result
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + result.score * 0.4
        for result in vector_results:
            merged.setdefault(result.chunk_id, result)
            scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + result.score * 0.6
        ranked = [MemorySearchResult(
            chunk_id=result.chunk_id,
            path=result.path,
            citation=result.citation,
            start_line=result.start_line,
            end_line=result.end_line,
            snippet=result.snippet,
            score=scores[chunk_id],
            match_type="hybrid",
            source=result.source,
        ) for chunk_id, result in merged.items()]
        ranked.sort(key=lambda result: result.score, reverse=True)
        return ranked[:limit]

    def _filter_min_score(self, results: list[MemorySearchResult], min_score: float | None, limit: int) -> list[MemorySearchResult]:
        threshold = float(min_score) if min_score is not None else None
        selected = [result for result in results if threshold is None or result.score >= threshold]
        return selected[:limit]

    def _safe_limit(self, limit: int) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError):
            return 5
        return min(max(value, 1), 20)

    def _result_from_payload(self, data: dict[str, object]) -> MemorySearchResult:
        return MemorySearchResult(
            chunk_id=str(data.get("chunk_id", "")),
            path=str(data.get("path", "")),
            citation=str(data.get("citation", "")),
            start_line=int(data.get("startLine", 1)),
            end_line=int(data.get("endLine", 1)),
            snippet=str(data.get("snippet", "")),
            score=float(data.get("score", 0.0)),
            match_type=str(data.get("matchType", "")),
            source=str(data.get("source", "memory")),
        )

    def _path_from_memory_id(self, memory_id: str) -> str:
        if memory_id == "profile_user":
            return "memory/USER.md"
        if memory_id == "memory_index":
            return "memory/MEMORY.md"
        if memory_id.startswith("daily_"):
            return f"memory/{memory_id.removeprefix('daily_').replace('_', '-')}.md"
        if memory_id.startswith("memory_"):
            return f"memory/topics/{memory_id.removeprefix('memory_')}.md"
        return memory_id
