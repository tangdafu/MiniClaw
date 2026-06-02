import json
import sqlite3
from pathlib import Path

from .embeddings import blob_to_vector, cosine_similarity, vector_to_blob
from .models import MemoryChunk, MemoryRecord, MemorySearchResult
from .text import normalize_search_text


class SQLiteMemoryIndex:
    def __init__(self, sqlite_path: Path):
        self.sqlite_path = Path(sqlite_path)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT,
                    content_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_chunks (
                    id TEXT PRIMARY KEY,
                    memory_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    start_char INTEGER NOT NULL,
                    end_char INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memories(id)
                );

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    chunk_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector_blob BLOB NOT NULL,
                    PRIMARY KEY(chunk_id, model),
                    FOREIGN KEY(chunk_id) REFERENCES memory_chunks(id)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    chunk_id UNINDEXED,
                    memory_id UNINDEXED,
                    title,
                    search_text
                );
                """
            )

    def index_memory(
        self,
        record: MemoryRecord,
        chunks: list[MemoryChunk],
        embeddings: dict[str, tuple[str, list[float]]] | None = None,
    ) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (record.id,))
            conn.execute("DELETE FROM memory_embeddings WHERE chunk_id IN (SELECT id FROM memory_chunks WHERE memory_id = ?)", (record.id,))
            conn.execute("DELETE FROM memory_chunks WHERE memory_id = ?", (record.id,))
            conn.execute(
                """
                INSERT OR REPLACE INTO memories (
                    id, path, type, title, tags_json, source, confidence,
                    created_at, updated_at, deleted_at, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    record.id,
                    record.path,
                    record.type,
                    record.title,
                    json.dumps(record.tags, ensure_ascii=False),
                    record.source,
                    record.confidence,
                    record.created_at,
                    record.updated_at,
                    record.content_hash,
                ),
            )

            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO memory_chunks (
                        id, memory_id, chunk_index, start_char, end_char, content, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk.id,
                        chunk.memory_id,
                        chunk.chunk_index,
                        chunk.start_char,
                        chunk.end_char,
                        chunk.content,
                        chunk.content_hash,
                    ),
                )
                conn.execute(
                    "INSERT INTO memory_fts (chunk_id, memory_id, title, search_text) VALUES (?, ?, ?, ?)",
                    (chunk.id, chunk.memory_id, record.title, normalize_search_text(f"{record.title} {chunk.content}")),
                )

                if embeddings and chunk.id in embeddings:
                    model, vector = embeddings[chunk.id]
                    conn.execute(
                        """
                        INSERT INTO memory_embeddings (chunk_id, model, dimension, vector_blob)
                        VALUES (?, ?, ?, ?)
                        """,
                        (chunk.id, model, len(vector), vector_to_blob(vector)),
                    )

    def memory_content_hash(self, memory_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT content_hash FROM memories WHERE id = ? AND deleted_at IS NULL",
                (memory_id,),
            ).fetchone()
            return row["content_hash"] if row else None

    def clear_active_index(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM memory_fts")
            conn.execute("DELETE FROM memory_embeddings")
            conn.execute("DELETE FROM memory_chunks")
            conn.execute("DELETE FROM memories WHERE deleted_at IS NULL")

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE id = ? AND deleted_at IS NULL", (memory_id,)).fetchone()
            return self._record_from_row(row) if row else None

    def forget_memory(self, memory_id: str, deleted_at: str, trash_path: str | None = None) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT id FROM memories WHERE id = ? AND deleted_at IS NULL", (memory_id,)).fetchone()
            if not row:
                return False
            if trash_path:
                conn.execute(
                    "UPDATE memories SET deleted_at = ?, path = ? WHERE id = ?",
                    (deleted_at, trash_path, memory_id),
                )
            else:
                conn.execute("UPDATE memories SET deleted_at = ? WHERE id = ?", (deleted_at, memory_id))
            return True

    def search_fts(self, query: str, limit: int = 5, memory_type: str | None = None) -> tuple[list[MemorySearchResult], str | None]:
        normalized = normalize_search_text(query)
        if not normalized:
            return [], None

        sql = """
            SELECT
                c.id AS chunk_id,
                c.memory_id,
                c.chunk_index,
                c.start_char,
                c.end_char,
                c.content,
                m.path,
                m.title,
                m.type,
                m.tags_json,
                bm25(memory_fts) AS raw_score
            FROM memory_fts
            JOIN memory_chunks c ON c.id = memory_fts.chunk_id
            JOIN memories m ON m.id = c.memory_id
            WHERE memory_fts MATCH ? AND m.deleted_at IS NULL
        """
        params: list[object] = [normalized]
        if memory_type:
            sql += " AND m.type = ?"
            params.append(memory_type)
        sql += " ORDER BY raw_score LIMIT ?"
        params.append(limit)

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._search_result_from_row(row, "fts", self._normalize_fts_score(row["raw_score"])) for row in rows], None

    def search_vector(
        self,
        query_vector: list[float],
        model: str,
        limit: int = 5,
        memory_type: str | None = None,
    ) -> list[MemorySearchResult]:
        sql = """
            SELECT
                c.id AS chunk_id,
                c.memory_id,
                c.chunk_index,
                c.start_char,
                c.end_char,
                c.content,
                m.path,
                m.title,
                m.type,
                m.tags_json,
                e.dimension,
                e.vector_blob
            FROM memory_embeddings e
            JOIN memory_chunks c ON c.id = e.chunk_id
            JOIN memories m ON m.id = c.memory_id
            WHERE e.model = ? AND m.deleted_at IS NULL
        """
        params: list[object] = [model]
        if memory_type:
            sql += " AND m.type = ?"
            params.append(memory_type)

        results: list[MemorySearchResult] = []
        with self.connect() as conn:
            for row in conn.execute(sql, params).fetchall():
                vector = blob_to_vector(row["vector_blob"], row["dimension"])
                score = cosine_similarity(query_vector, vector)
                results.append(self._search_result_from_row(row, "vector", score))

        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]

    def _record_from_row(self, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            path=row["path"],
            type=row["type"],
            title=row["title"],
            tags=json.loads(row["tags_json"]),
            source=row["source"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            content_hash=row["content_hash"],
        )

    def _search_result_from_row(self, row: sqlite3.Row, match_type: str, score: float) -> MemorySearchResult:
        return MemorySearchResult(
            memory_id=row["memory_id"],
            chunk_id=row["chunk_id"],
            path=row["path"],
            title=row["title"],
            type=row["type"],
            tags=json.loads(row["tags_json"]),
            score=float(score),
            match_type=match_type,
            excerpt=row["content"],
            chunk_index=row["chunk_index"],
            start_char=row["start_char"],
            end_char=row["end_char"],
        )

    def _normalize_fts_score(self, raw_score: float) -> float:
        return 1.0 / (1.0 + abs(float(raw_score)))
