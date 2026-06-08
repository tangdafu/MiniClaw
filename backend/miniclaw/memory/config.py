import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemoryConfig:
    memory_dir: Path
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    chunk_size: int = 1000
    chunk_overlap: int = 100
    prompt_injection_enabled: bool = True
    prompt_max_chars: int = 12_000

    @classmethod
    def from_env(cls) -> "MemoryConfig":
        backend_dir = Path(__file__).resolve().parents[2]
        memory_dir = Path(os.getenv("MINICLAW_MEMORY_DIR", str(backend_dir / "memories")))
        if not memory_dir.is_absolute():
            memory_dir = backend_dir / memory_dir

        return cls(
            memory_dir=memory_dir,
            embedding_model=os.getenv("MINICLAW_EMBEDDING_MODEL") or None,
            embedding_base_url=os.getenv("MINICLAW_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None,
            embedding_api_key=os.getenv("MINICLAW_EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
            prompt_injection_enabled=_bool_env("MINICLAW_MEMORY_PROMPT_ENABLED", True),
            prompt_max_chars=_positive_int_env("MINICLAW_MEMORY_PROMPT_MAX_CHARS", 12_000),
        )

    @property
    def sqlite_path(self) -> Path:
        return self.memory_dir / "memory.sqlite"

    @property
    def embeddings_enabled(self) -> bool:
        return bool(self.embedding_model and self.embedding_api_key)


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
