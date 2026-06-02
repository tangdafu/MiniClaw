import math
import struct
from typing import Protocol

from openai import AsyncOpenAI

from .config import MemoryConfig


class EmbeddingProvider(Protocol):
    model: str

    @property
    def available(self) -> bool:
        ...

    async def embed(self, text: str) -> list[float]:
        ...


class OpenAIEmbeddingProvider:
    def __init__(self, config: MemoryConfig):
        self.model = config.embedding_model or ""
        self.client = AsyncOpenAI(
            api_key=config.embedding_api_key,
            base_url=config.embedding_base_url,
        ) if config.embeddings_enabled else None

    @property
    def available(self) -> bool:
        return self.client is not None and bool(self.model)

    async def embed(self, text: str) -> list[float]:
        if not self.available or self.client is None:
            raise RuntimeError("Embeddings are not configured")
        response = await self.client.embeddings.create(model=self.model, input=text)
        return list(response.data[0].embedding)


class FakeEmbeddingProvider:
    def __init__(self, model: str = "fake-embedding"):
        self.model = model

    @property
    def available(self) -> bool:
        return True

    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        return [
            float("frontend" in lowered or "ui" in lowered or "前端" in text),
            float("memory" in lowered or "markdown" in lowered or "记忆" in text),
            float(sum(1 for char in text if "\u4e00" <= char <= "\u9fff")),
            float(len(text)) / 100.0,
        ]


def vector_to_blob(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def blob_to_vector(blob: bytes, dimension: int) -> list[float]:
    if dimension <= 0:
        return []
    return list(struct.unpack(f"<{dimension}f", blob))


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
