from ..types import Tool
from .service import MemoryService


def get_memory_tools(service: MemoryService) -> list[Tool]:
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
        record = await service.remember(
            title=title,
            content=content,
            memory_type=memory_type,
            topic=topic,
            memory_date=memory_date,
            tags=tags or [],
            source=source,
            confidence=confidence,
        )
        return service.format_record(record)

    async def search_memory(
        query: str,
        mode: str = "hybrid",
        memory_type: str | None = None,
        limit: int = 5,
    ) -> str:
        results, warning = await service.search(query=query, mode=mode, memory_type=memory_type, limit=limit)
        return service.format_search_results(results, warning=warning)

    def read_memory(memory_id: str) -> str:
        return service.read_memory(memory_id)

    def forget_memory(memory_id: str) -> str:
        return service.forget_memory(memory_id)

    async def reindex_memories() -> str:
        return service.format_reindex_result(await service.reindex_all_memories())

    return [
        Tool(
            name="remember",
            description="保存长期记忆。memory_type 支持 profile、memory、daily：profile 固定写入 profile/user.md，memory 按 topic 写入 memory/<topic>.md，daily 按日期写入 daily/YYYY-MM-DD.md。profile 适合用户稳定偏好和身份信息，memory 适合主题级长期事实，daily 适合当天摘要。重复 content 不会再次追加。",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "记忆标题"},
                    "content": {"type": "string", "description": "记忆正文"},
                    "memory_type": {"type": "string", "description": "记忆范围：profile、memory 或 daily，默认 memory。旧的 preference 会归入 profile，project/note 会归入 memory。"},
                    "topic": {"type": "string", "description": "memory 类型的主题文件名，如 frontend_design、backend_architecture、前端设计"},
                    "memory_date": {"type": "string", "description": "daily 类型日期，格式 YYYY-MM-DD，默认今天"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
                    "source": {"type": "string", "description": "来源，默认 user_explicit"},
                    "confidence": {"type": "number", "description": "置信度，默认 0.9"},
                },
                "required": ["title", "content"],
            },
            handler=remember,
        ),
        Tool(
            name="search_memory",
            description="搜索长期记忆，返回相关片段。mode 支持 fts、vector、hybrid。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "mode": {"type": "string", "description": "fts、vector 或 hybrid，默认 hybrid"},
                    "memory_type": {"type": "string", "description": "可选记忆类型过滤"},
                    "limit": {"type": "integer", "description": "最多返回条数，默认 5"},
                },
                "required": ["query"],
            },
            handler=search_memory,
        ),
        Tool(
            name="read_memory",
            description="按 memory_id 读取完整 Markdown 记忆文档。",
            parameters={
                "type": "object",
                "properties": {"memory_id": {"type": "string", "description": "记忆 ID"}},
                "required": ["memory_id"],
            },
            handler=read_memory,
        ),
        Tool(
            name="forget_memory",
            description="按 memory_id 删除/遗忘整个 scoped Markdown 记忆文档，使其不再出现在检索结果中。注意：profile_user 会删除整个 profile/user.md，memory_<topic> 会删除整个主题文件。",
            parameters={
                "type": "object",
                "properties": {"memory_id": {"type": "string", "description": "记忆 ID"}},
                "required": ["memory_id"],
            },
            handler=forget_memory,
        ),
        Tool(
            name="reindex_memories",
            description="从 Markdown 权威文件重建长期记忆 SQLite 索引。用于手动编辑 Markdown 或索引损坏后的修复。不会索引 .trash 中的已删除记忆。",
            parameters={"type": "object", "properties": {}},
            handler=reindex_memories,
        ),
    ]
