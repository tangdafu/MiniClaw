from ..types import Tool
from .service import MemoryService


def get_memory_tools(service: MemoryService) -> list[Tool]:
    async def memory_search(query: str, max_results: int | None = None, min_score: float | None = None, mode: str = "hybrid") -> str:
        return await service.memory_search(query=query, max_results=max_results, min_score=min_score, mode=mode)

    def memory_get(path: str, from_line: int | None = None, lines: int | None = None) -> str:
        return service.memory_get(path=path, from_line=from_line, lines=lines)

    def memory_write(path: str, content: str, append: bool = False) -> str:
        return service.memory_write(path=path, content=content, append=append)

    def memory_edit(path: str, oldText: str, newText: str) -> str:
        return service.memory_edit(path=path, old_text=oldText, new_text=newText)

    async def memory_reindex() -> str:
        return await service.memory_reindex()

    async def remember(
        title: str,
        content: str,
        memory_type: str = "memory",
        topic: str | None = None,
        memory_date: str | None = None,
        tags: list[str] | None = None,
        source: str = "user_explicit",
        confidence: float = 0.9,
    ) -> str:
        record = await service.remember(title, content, memory_type, topic, memory_date, tags or [], source, confidence)
        return service.format_record(record)

    async def search_memory(query: str, mode: str = "hybrid", memory_type: str | None = None, limit: int = 5) -> str:
        del memory_type
        return await service.memory_search(query=query, max_results=limit, mode=mode)

    def read_memory(memory_id: str) -> str:
        return service.read_memory(memory_id)

    def forget_memory(memory_id: str) -> str:
        return service.forget_memory(memory_id)

    async def reindex_memories() -> str:
        return await service.memory_reindex()

    return [
        Tool(
            name="memory_search",
            description="Search local long-term memory Markdown files before answering questions about previous decisions, user preferences, prior work, dates, people, or todos. Results include path and line citations; call memory_get with the returned path/lines before editing or when more context is needed.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query describing the memory to retrieve."},
                    "max_results": {"type": "integer", "description": "Maximum results, 1-20. Default 5."},
                    "min_score": {"type": "number", "description": "Optional minimum relevance score."},
                    "mode": {"type": "string", "description": "fts, vector, or hybrid. Default hybrid."},
                },
                "required": ["query"],
            },
            handler=memory_search,
        ),
        Tool(
            name="memory_get",
            description="Read a safe memory Markdown file, optionally by line range. Use after memory_search to inspect the exact cited memory before relying on or editing it.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Safe memory path: memory/MEMORY.md, memory/USER.md, memory/YYYY-MM-DD.md, or memory/topics/<topic>.md."},
                    "from_line": {"type": "integer", "description": "Optional 1-based starting line."},
                    "lines": {"type": "integer", "description": "Optional number of lines to read."},
                },
                "required": ["path"],
            },
            handler=memory_get,
        ),
        Tool(
            name="memory_write",
            description="Write or append to a safe memory Markdown file. This modifies Markdown only; SQLite search index is updated by synchronization. Use append=true for daily notes or adding entries; use memory_edit for precise updates.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Safe memory path: memory/MEMORY.md, memory/USER.md, memory/YYYY-MM-DD.md, or memory/topics/<topic>.md."},
                    "content": {"type": "string", "description": "Markdown content to write or append."},
                    "append": {"type": "boolean", "description": "Append instead of replacing the file. Default false."},
                },
                "required": ["path", "content"],
            },
            handler=memory_write,
        ),
        Tool(
            name="memory_edit",
            description="Precisely edit a safe memory Markdown file by replacing oldText with newText. Call memory_get first and provide exact oldText. The edit fails if oldText is missing or appears multiple times.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Safe memory Markdown path."},
                    "oldText": {"type": "string", "description": "Exact existing text to replace. Must appear exactly once."},
                    "newText": {"type": "string", "description": "Replacement text."},
                },
                "required": ["path", "oldText", "newText"],
            },
            handler=memory_edit,
        ),
        Tool(
            name="memory_reindex",
            description="Rebuild the SQLite memory index from Markdown memory files. Use after manual Markdown edits or when search appears stale.",
            parameters={"type": "object", "properties": {}},
            handler=memory_reindex,
        ),
        Tool(
            name="remember",
            description="Compatibility alias for old memory writes. Prefer memory_write or memory_edit. Stores content in memory/USER.md, memory/YYYY-MM-DD.md, or memory/topics/<topic>.md.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "memory_type": {"type": "string"},
                    "topic": {"type": "string"},
                    "memory_date": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "source": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["title", "content"],
            },
            handler=remember,
        ),
        Tool(
            name="search_memory",
            description="Compatibility alias for memory_search. Prefer memory_search.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "mode": {"type": "string"},
                    "memory_type": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["query"],
            },
            handler=search_memory,
        ),
        Tool(
            name="read_memory",
            description="Compatibility alias for old memory ID reads. Prefer memory_get with a path and optional line range.",
            parameters={"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]},
            handler=read_memory,
        ),
        Tool(
            name="forget_memory",
            description="Compatibility alias for deleting an old memory ID. Prefer memory_edit or explicit file management when possible.",
            parameters={"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]},
            handler=forget_memory,
        ),
        Tool(
            name="reindex_memories",
            description="Compatibility alias for memory_reindex. Prefer memory_reindex.",
            parameters={"type": "object", "properties": {}},
            handler=reindex_memories,
        ),
    ]
