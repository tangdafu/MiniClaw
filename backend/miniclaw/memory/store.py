import hashlib
from dataclasses import dataclass, field
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from .models import MemoryRecord


INVALID_PATH_CHARS = set('<>:"/\\|?*')
MEMORY_TYPES = {"profile", "memory", "daily"}
TYPE_ALIASES = {
    "preference": "profile",
    "preferences": "profile",
    "note": "memory",
    "notes": "memory",
    "project": "memory",
    "projects": "memory",
}


@dataclass(frozen=True)
class MarkdownMemoryDocument:
    frontmatter: dict[str, object] = field(default_factory=dict)
    body: str = ""


class MarkdownMemoryStore:
    def __init__(self, memory_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        (self.memory_dir / ".trash").mkdir(parents=True, exist_ok=True)

    def create(
        self,
        title: str,
        content: str,
        memory_type: str = "memory",
        topic: str | None = None,
        memory_date: str | None = None,
        tags: list[str] | None = None,
        source: str = "user_explicit",
        confidence: float = 0.9,
    ) -> tuple[MemoryRecord, str]:
        safe_type = self.normalize_memory_type(memory_type)
        relative_path = self.path_for(safe_type, title=title, topic=topic, memory_date=memory_date)
        memory_id = self.id_for(safe_type, relative_path)
        now = datetime.now(timezone.utc).isoformat()
        existing_body = ""
        created_at = now
        target = self.resolve_relative(relative_path)
        if target.exists():
            existing_document = self.parse_markdown(target.read_text(encoding="utf-8"))
            existing_body = existing_document.body
            created_at = str(existing_document.frontmatter.get("created_at") or now)
        body = self.merge_body(existing_body, content, safe_type)

        record = MemoryRecord(
            id=memory_id,
            path=relative_path,
            type=safe_type,
            title=title.strip() or "Untitled memory",
            tags=tags or [],
            source=source,
            confidence=float(confidence),
            created_at=created_at,
            updated_at=now,
            content_hash=self.hash_text(body),
        )

        target.parent.mkdir(parents=True, exist_ok=True)
        markdown = self.render_markdown(record, body)
        target.write_text(markdown, encoding="utf-8")
        return record, markdown

    def read_by_path(self, relative_path: str) -> str:
        target = self.resolve_relative(relative_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(relative_path)
        return target.read_text(encoding="utf-8")

    def iter_memory_files(self) -> list[Path]:
        if not self.memory_dir.exists():
            return []
        return sorted(
            path for path in self.memory_dir.rglob("*.md")
            if path.is_file() and ".trash" not in path.relative_to(self.memory_dir).parts
        )

    def forget(self, relative_path: str, memory_id: str) -> str:
        source = self.resolve_relative(relative_path)
        trash_relative = f".trash/{memory_id}.md"
        target = self.resolve_relative(trash_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.exists() and source.is_file():
            if target.exists():
                target.unlink()
            shutil.move(str(source), str(target))
        return trash_relative

    def resolve_relative(self, relative_path: str) -> Path:
        target = (self.memory_dir / relative_path).resolve()
        root = self.memory_dir.resolve()
        if root != target and root not in target.parents:
            raise ValueError("Memory path escapes memory directory")
        return target

    def render_markdown(self, record: MemoryRecord, content: str) -> str:
        tag_lines = "\n".join(f"  - {tag}" for tag in record.tags) or "  []"
        return (
            "---\n"
            f"id: {record.id}\n"
            f"type: {record.type}\n"
            f"title: {record.title}\n"
            "tags:\n"
            f"{tag_lines}\n"
            f"source: {record.source}\n"
            f"confidence: {record.confidence}\n"
            f"created_at: {record.created_at}\n"
            f"updated_at: {record.updated_at}\n"
            f"content_hash: {record.content_hash}\n"
            "---\n\n"
            f"{content.strip()}\n"
        )

    def record_from_markdown(self, relative_path: str, markdown: str) -> MemoryRecord:
        document = self.parse_markdown(markdown)
        memory_type = self.normalize_memory_type(str(document.frontmatter.get("type") or "memory"))
        memory_id = str(document.frontmatter.get("id") or self.id_for(memory_type, relative_path))
        title = str(document.frontmatter.get("title") or Path(relative_path).stem or "Untitled memory")
        tags = document.frontmatter.get("tags")
        if not isinstance(tags, list):
            tags = []
        content_hash = str(document.frontmatter.get("content_hash") or self.hash_text(document.body))
        now = datetime.now(timezone.utc).isoformat()
        return MemoryRecord(
            id=memory_id,
            path=relative_path,
            type=memory_type,
            title=title,
            tags=[str(tag) for tag in tags],
            source=str(document.frontmatter.get("source") or "user_explicit"),
            confidence=self.parse_float(document.frontmatter.get("confidence"), 0.9),
            created_at=str(document.frontmatter.get("created_at") or now),
            updated_at=str(document.frontmatter.get("updated_at") or now),
            content_hash=content_hash,
        )

    def generate_memory_id(self) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"mem_{stamp}_{uuid.uuid4().hex[:8]}"

    def id_for(self, memory_type: str, relative_path: str) -> str:
        if memory_type == "profile":
            return "profile_user"
        if memory_type == "daily":
            return f"daily_{Path(relative_path).stem.replace('-', '_')}"
        if Path(relative_path).stem.startswith("mem_"):
            return Path(relative_path).stem
        return f"memory_{Path(relative_path).stem}"

    def path_for(self, memory_type: str, title: str, topic: str | None, memory_date: str | None) -> str:
        if memory_type == "profile":
            return "profile/user.md"
        if memory_type == "daily":
            day = memory_date or date.today().isoformat()
            return f"daily/{self.safe_name(day)}.md"
        safe_topic = self.safe_name(topic or title)
        if not safe_topic:
            return f"memory/{self.generate_memory_id()}.md"
        return f"memory/{safe_topic}.md"

    def normalize_memory_type(self, memory_type: str | None) -> str:
        normalized = self.safe_name(memory_type or "memory") or "memory"
        normalized = TYPE_ALIASES.get(normalized, normalized)
        if normalized not in MEMORY_TYPES:
            return "memory"
        return normalized

    def safe_name(self, value: str) -> str:
        cleaned = []
        previous_was_separator = False
        for char in (value or "").strip():
            if char.isspace() or char in INVALID_PATH_CHARS:
                if not previous_was_separator:
                    cleaned.append("_")
                    previous_was_separator = True
                continue
            if ord(char) < 32:
                continue
            cleaned.append(char)
            previous_was_separator = False
        return "".join(cleaned).strip("._-").lower()

    def merge_body(self, existing_body: str, new_content: str, memory_type: str) -> str:
        new_body = new_content.strip()
        if not existing_body.strip():
            return new_body
        if not new_body:
            return existing_body.strip()
        if new_body in existing_body:
            return existing_body.strip()
        timestamp = datetime.now(timezone.utc).isoformat()
        heading = {
            "profile": "Profile Update",
            "memory": "Topic Update",
            "daily": "Daily Entry",
        }.get(memory_type, "Update")
        return f"{existing_body.strip()}\n\n## {heading} {timestamp}\n\n{new_body}"

    def body_from_markdown(self, markdown: str) -> str:
        return self.parse_markdown(markdown).body

    def frontmatter_value(self, markdown: str, key: str) -> str | None:
        value = self.parse_markdown(markdown).frontmatter.get(key)
        return str(value) if value is not None else None

    def parse_markdown(self, markdown: str) -> MarkdownMemoryDocument:
        if not markdown.startswith("---"):
            return MarkdownMemoryDocument(body=markdown.strip())
        parts = markdown.split("---", 2)
        if len(parts) != 3:
            return MarkdownMemoryDocument(body=markdown.strip())

        frontmatter: dict[str, object] = {}
        current_list_key: str | None = None
        for raw_line in parts[1].splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                continue
            if current_list_key and stripped.startswith("-"):
                value = stripped[1:].strip()
                if value:
                    cast_list = frontmatter.setdefault(current_list_key, [])
                    if isinstance(cast_list, list):
                        cast_list.append(value)
                continue
            current_list_key = None
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            key = key.strip()
            value = raw_value.strip()
            if not key:
                continue
            if value == "":
                frontmatter[key] = []
                current_list_key = key
            elif value == "[]":
                frontmatter[key] = []
            else:
                frontmatter[key] = value
        return MarkdownMemoryDocument(frontmatter=frontmatter, body=parts[2].strip())

    def parse_float(self, value: object, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
