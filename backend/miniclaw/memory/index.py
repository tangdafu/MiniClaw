import sqlite3
from pathlib import Path

from .embeddings import blob_to_vector, cosine_similarity, vector_to_blob
from .models import MemoryChunk, MemoryFileEntry, MemorySearchResult
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
                CREATE TABLE IF NOT EXISTS memory_files (
                    path TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    mtime INTEGER NOT NULL,
                    size INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_chunks (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL,
                    source TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    chunk_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector_blob BLOB NOT NULL,
                    PRIMARY KEY(chunk_id, model)
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                    chunk_id UNINDEXED,
                    path UNINDEXED,
                    source UNINDEXED,
                    search_text
                );
                """
            )

    def index_file(
        self,
        entry: MemoryFileEntry,
        chunks: list[MemoryChunk],
        embeddings: dict[str, tuple[str, list[float]]] | None = None,
    ) -> None:
        with self.connect() as conn:
            self._delete_path(conn, entry.path)
            conn.execute(
                "INSERT OR REPLACE INTO memory_files (path, source, hash, mtime, size) VALUES (?, ?, ?, ?, ?)",
                (entry.path, entry.source, entry.content_hash, entry.mtime_ms, entry.size),
            )
            for chunk in chunks:
                conn.execute(
                    """
                    INSERT INTO memory_chunks (id, path, source, start_line, end_line, content, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (chunk.id, chunk.path, chunk.source, chunk.start_line, chunk.end_line, chunk.text, chunk.content_hash),
                )
                conn.execute(
                    "INSERT INTO memory_fts (chunk_id, path, source, search_text) VALUES (?, ?, ?, ?)",
                    (chunk.id, chunk.path, chunk.source, normalize_search_text(chunk.text)),
                )
                if embeddings and chunk.id in embeddings:
                    model, vector = embeddings[chunk.id]
                    conn.execute(
                        "INSERT INTO memory_embeddings (chunk_id, model, dimension, vector_blob) VALUES (?, ?, ?, ?)",
                        (chunk.id, model, len(vector), vector_to_blob(vector)),
                    )

    def remove_file(self, path: str) -> None:
        with self.connect() as conn:
            self._delete_path(conn, path)

    def clear_active_index(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM memory_fts")
            conn.execute("DELETE FROM memory_embeddings")
            conn.execute("DELETE FROM memory_chunks")
            conn.execute("DELETE FROM memory_files")

    def file_hash(self, path: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT hash FROM memory_files WHERE path = ?", (path,)).fetchone()
            return row["hash"] if row else None

    def indexed_paths(self) -> set[str]:
        with self.connect() as conn:
            return {row["path"] for row in conn.execute("SELECT path FROM memory_files").fetchall()}

    def search_fts(self, query: str, limit: int = 5) -> tuple[list[MemorySearchResult], str | None]:
        normalized = normalize_search_text(query)
        if not normalized:
            return [], None
        sql = """
            SELECT c.id AS chunk_id, c.path, c.source, c.start_line, c.end_line, c.content, bm25(memory_fts) AS raw_score
            FROM memory_fts
            JOIN memory_chunks c ON c.id = memory_fts.chunk_id
            WHERE memory_fts MATCH ?
            ORDER BY raw_score LIMIT ?
        """
        with self.connect() as conn:
            rows = conn.execute(sql, (normalized, limit)).fetchall()
        return [self._search_result_from_row(row, "fts", self._normalize_fts_score(row["raw_score"])) for row in rows], None

    def search_vector(self, query_vector: list[float], model: str, limit: int = 5) -> list[MemorySearchResult]:
        sql = """
            SELECT c.id AS chunk_id, c.path, c.source, c.start_line, c.end_line, c.content, e.dimension, e.vector_blob
            FROM memory_embeddings e
            JOIN memory_chunks c ON c.id = e.chunk_id
            WHERE e.model = ?
        """
        results: list[MemorySearchResult] = []
        with self.connect() as conn:
            for row in conn.execute(sql, (model,)).fetchall():
                vector = blob_to_vector(row["vector_blob"], row["dimension"])
                score = cosine_similarity(query_vector, vector)
                results.append(self._search_result_from_row(row, "vector", score))
        results.sort(key=lambda result: result.score, reverse=True)
        return results[:limit]

    def _delete_path(self, conn: sqlite3.Connection, path: str) -> None:
        conn.execute("DELETE FROM memory_fts WHERE path = ?", (path,))
        conn.execute("DELETE FROM memory_embeddings WHERE chunk_id IN (SELECT id FROM memory_chunks WHERE path = ?)", (path,))
        conn.execute("DELETE FROM memory_chunks WHERE path = ?", (path,))
        conn.execute("DELETE FROM memory_files WHERE path = ?", (path,))

    def _search_result_from_row(self, row: sqlite3.Row, match_type: str, score: float) -> MemorySearchResult:
        start_line = int(row["start_line"])
        end_line = int(row["end_line"])
        citation = f"{row['path']}#L{start_line}" if start_line == end_line else f"{row['path']}#L{start_line}-L{end_line}"
        return MemorySearchResult(
            chunk_id=row["chunk_id"],
            path=row["path"],
            citation=citation,
            start_line=start_line,
            end_line=end_line,
            snippet=row["content"],
            score=float(score),
            match_type=match_type,
            source=row["source"],
        )

    def _normalize_fts_score(self, raw_score: float) -> float:
        return 1.0 / (1.0 + abs(float(raw_score)))
