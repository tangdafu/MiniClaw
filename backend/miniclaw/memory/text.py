import hashlib
import re

from .models import MemoryChunk


ASCII_RE = re.compile(r"[A-Za-z0-9_./:-]+")


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_text(path: str, content: str, chunk_size: int = 1000, overlap: int = 100, source: str = "memory") -> list[MemoryChunk]:
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
        chunk_id = f"{path}:{index}"
        chunks.append(
            MemoryChunk(
                id=chunk_id,
                path=path,
                source=source,
                start_line=1,
                end_line=1,
                text=chunk_content,
                content_hash=hash_text(chunk_content),
            )
        )
        if end >= len(body):
            break
        start += step
        index += 1

    return chunks


def chunk_markdown(path: str, content: str, chunk_size: int = 1000, overlap: int = 100, source: str = "memory") -> list[MemoryChunk]:
    lines = content.splitlines() or [""]
    chunks: list[MemoryChunk] = []
    current: list[str] = []
    current_chars = 0
    start_line = 1
    index = 0
    overlap_lines = max(0, overlap // 80)

    for line_number, line in enumerate(lines, 1):
        line_chars = len(line) + 1
        if current and current_chars + line_chars > chunk_size:
            text = "\n".join(current)
            chunks.append(MemoryChunk(
                id=f"{path}:{start_line}:{line_number - 1}",
                path=path,
                source=source,
                start_line=start_line,
                end_line=line_number - 1,
                text=text,
                content_hash=hash_text(text),
            ))
            carry = current[-overlap_lines:] if overlap_lines else []
            current = list(carry)
            current_chars = sum(len(value) + 1 for value in current)
            start_line = line_number - len(current)
            index += 1
        current.append(line)
        current_chars += line_chars

    if current:
        text = "\n".join(current)
        chunks.append(MemoryChunk(
            id=f"{path}:{start_line}:{len(lines)}" if index == 0 else f"{path}:{start_line}:{len(lines)}",
            path=path,
            source=source,
            start_line=start_line,
            end_line=len(lines),
            text=text,
            content_hash=hash_text(text),
        ))
    return chunks


def normalize_search_text(text: str) -> str:
    tokens: list[str] = []
    tokens.extend(match.group(0).lower() for match in ASCII_RE.finditer(text))

    chars = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    tokens.extend(chars)
    tokens.extend("".join(chars[index:index + 2]) for index in range(len(chars) - 1))

    return " ".join(token for token in tokens if token.strip())
