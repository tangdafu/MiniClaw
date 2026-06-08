from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemoryFileEntry:
    path: str
    absolute_path: str
    source: str
    content_hash: str
    mtime_ms: int
    size: int


@dataclass(frozen=True)
class MemoryChunk:
    id: str
    path: str
    source: str
    start_line: int
    end_line: int
    text: str
    content_hash: str


@dataclass(frozen=True)
class MemorySearchResult:
    chunk_id: str
    path: str
    citation: str
    start_line: int
    end_line: int
    snippet: str
    score: float
    match_type: str
    source: str = "memory"


@dataclass(frozen=True)
class MemoryRecord:
    """Compatibility record for old memory tool aliases."""

    id: str
    path: str
    type: str
    title: str
    tags: list[str] = field(default_factory=list)
    source: str = "user_explicit"
    confidence: float = 0.9
    created_at: str = ""
    updated_at: str = ""
    content_hash: str = ""
