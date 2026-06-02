from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemoryRecord:
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


@dataclass(frozen=True)
class MemoryChunk:
    id: str
    memory_id: str
    chunk_index: int
    start_char: int
    end_char: int
    content: str
    content_hash: str


@dataclass(frozen=True)
class MemorySearchResult:
    memory_id: str
    chunk_id: str
    path: str
    title: str
    type: str
    tags: list[str]
    score: float
    match_type: str
    excerpt: str
    chunk_index: int
    start_char: int
    end_char: int
