import hashlib
import re

from .models import MemoryChunk


ASCII_RE = re.compile(r"[A-Za-z0-9_./:-]+")


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(memory_id: str, content: str, chunk_size: int = 1000, overlap: int = 100) -> list[MemoryChunk]:
    body = content.strip()
    if not body:
        body = ""

    chunks: list[MemoryChunk] = []
    start = 0
    index = 0
    step = max(1, chunk_size - max(0, overlap))

    while start < len(body) or (not chunks and body == ""):
        end = min(len(body), start + chunk_size)
        chunk_content = body[start:end]
        chunk_id = f"{memory_id}_chunk_{index}"
        chunks.append(
            MemoryChunk(
                id=chunk_id,
                memory_id=memory_id,
                chunk_index=index,
                start_char=start,
                end_char=end,
                content=chunk_content,
                content_hash=hash_text(chunk_content),
            )
        )
        if end >= len(body):
            break
        start += step
        index += 1

    return chunks


def normalize_search_text(text: str) -> str:
    tokens: list[str] = []
    tokens.extend(match.group(0).lower() for match in ASCII_RE.finditer(text))

    chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    tokens.extend(chars)
    tokens.extend("".join(chars[index:index + 2]) for index in range(len(chars) - 1))

    return " ".join(token for token in tokens if token.strip())
