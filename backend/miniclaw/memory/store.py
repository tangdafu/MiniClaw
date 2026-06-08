import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .models import MemoryFileEntry, MemoryRecord
from .text import hash_text


DATE_FILE_RE = re.compile(r"^memory/\d{4}-\d{2}-\d{2}\.md$")
TOPIC_FILE_RE = re.compile(r"^memory/topics/[^/\\]+\.md$")
LEGACY_TYPE_ALIASES = {
    "preference": "profile",
    "preferences": "profile",
    "note": "memory",
    "notes": "memory",
    "project": "memory",
    "projects": "memory",
}


class MarkdownMemoryStore:
    def __init__(self, memory_dir: Path):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_root.mkdir(parents=True, exist_ok=True)
        self.topics_dir.mkdir(parents=True, exist_ok=True)

    @property
    def memory_root(self) -> Path:
        return self.memory_dir / "memory"

    @property
    def topics_dir(self) -> Path:
        return self.memory_root / "topics"

    def validate_memory_path(self, path: str) -> str:
        normalized = (path or "").replace("\\", "/").strip()
        if not normalized:
            raise ValueError("Memory path is required")
        if ".." in normalized.split("/") or normalized.startswith("/"):
            raise ValueError("Invalid memory path: traversal and absolute paths are not allowed")
        if len(normalized) >= 2 and normalized[1] == ":":
            raise ValueError("Invalid memory path: absolute paths are not allowed")
        if not normalized.endswith(".md"):
            raise ValueError("Memory path must be a Markdown file ending in .md")
        if normalized in {"memory/MEMORY.md", "memory/USER.md"}:
            return normalized
        if DATE_FILE_RE.match(normalized) or TOPIC_FILE_RE.match(normalized):
            return normalized
        raise ValueError("Memory path must be memory/MEMORY.md, memory/USER.md, memory/YYYY-MM-DD.md, or memory/topics/<topic>.md")

    def resolve(self, path: str) -> Path:
        normalized = self.validate_memory_path(path)
        target = (self.memory_dir / normalized).resolve()
        root = self.memory_dir.resolve()
        if root != target and root not in target.parents:
            raise ValueError("Memory path escapes memory directory")
        return target

    def read_file(self, path: str, from_line: int | None = None, lines: int | None = None) -> dict[str, object]:
        normalized = self.validate_memory_path(path)
        target = self.resolve(normalized)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(normalized)
        all_lines = target.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        total_lines = len(all_lines)
        start = max(0, int(from_line or 1) - 1)
        end = total_lines if lines is None else min(total_lines, start + max(0, int(lines)))
        selected = all_lines[start:end]
        return {
            "path": normalized,
            "text": "".join(selected),
            "totalLines": total_lines,
            "fromLine": start + 1 if total_lines else 1,
            "toLine": start + len(selected),
            "truncated": end < total_lines,
        }

    def write_file(self, path: str, content: str, append: bool = False) -> dict[str, object]:
        normalized = self.validate_memory_path(path)
        target = self.resolve(normalized)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        mode = "a" if append else "w"
        with target.open(mode, encoding="utf-8") as handle:
            handle.write(str(content))
            if content and not str(content).endswith("\n"):
                handle.write("\n")
        self.update_memory_index_for_path(normalized)
        return {"success": True, "path": normalized, "appended": append, "fileExisted": existed}

    def edit_file(self, path: str, old_text: str, new_text: str) -> dict[str, object]:
        normalized = self.validate_memory_path(path)
        target = self.resolve(normalized)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(normalized)
        content = target.read_text(encoding="utf-8", errors="replace")
        if old_text not in content:
            return {"success": False, "path": normalized, "error": "oldText not found. Use memory_get to inspect the exact file content first."}
        occurrences = content.count(old_text)
        if occurrences > 1:
            return {"success": False, "path": normalized, "error": f"oldText appears {occurrences} times. Use a more specific replacement target."}
        target.write_text(content.replace(old_text, new_text, 1), encoding="utf-8")
        self.update_memory_index_for_path(normalized)
        return {"success": True, "path": normalized, "replaced": old_text, "with": new_text}

    def iter_memory_files(self) -> list[Path]:
        if not self.memory_root.exists():
            return []
        return sorted(path for path in self.memory_root.rglob("*.md") if path.is_file())

    def build_file_entry(self, path: Path) -> MemoryFileEntry:
        stat = path.stat()
        relative = path.relative_to(self.memory_dir).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace")
        return MemoryFileEntry(
            path=relative,
            absolute_path=str(path),
            source="memory",
            content_hash=hash_text(content),
            mtime_ms=int(stat.st_mtime * 1000),
            size=stat.st_size,
        )

    def update_memory_index_for_path(self, path: str) -> None:
        normalized = self.validate_memory_path(path)
        if not normalized.startswith("memory/topics/"):
            return
        index_path = self.resolve("memory/MEMORY.md")
        index_path.parent.mkdir(parents=True, exist_ok=True)
        topic_name = Path(normalized).stem
        entry = f"- [{topic_name}]({normalized.removeprefix('memory/')})"
        existing = index_path.read_text(encoding="utf-8", errors="replace") if index_path.exists() else "# Memory Index\n\n"
        if f"]({normalized.removeprefix('memory/')})" in existing:
            return
        if not existing.endswith("\n"):
            existing += "\n"
        index_path.write_text(f"{existing}{entry}\n", encoding="utf-8")

    def path_for_legacy(self, title: str, memory_type: str | None, topic: str | None, memory_date: str | None) -> str:
        normalized_type = self.safe_name(memory_type or "memory") or "memory"
        normalized_type = LEGACY_TYPE_ALIASES.get(normalized_type, normalized_type)
        if normalized_type == "profile":
            return "memory/USER.md"
        if normalized_type == "daily":
            return f"memory/{self.safe_name(memory_date or date.today().isoformat())}.md"
        return f"memory/topics/{self.safe_name(topic or title) or 'general'}.md"

    def legacy_record(self, path: str, title: str, memory_type: str | None = None) -> MemoryRecord:
        normalized = self.validate_memory_path(path)
        target = self.resolve(normalized)
        content = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        safe_type = LEGACY_TYPE_ALIASES.get(self.safe_name(memory_type or "memory"), self.safe_name(memory_type or "memory"))
        if normalized == "memory/USER.md":
            safe_type = "profile"
        elif DATE_FILE_RE.match(normalized):
            safe_type = "daily"
        else:
            safe_type = "memory"
        now = datetime.now(timezone.utc).isoformat()
        return MemoryRecord(
            id=self.memory_id_for_path(normalized),
            path=normalized,
            type=safe_type,
            title=title.strip() or Path(normalized).stem,
            created_at=now,
            updated_at=now,
            content_hash=hash_text(content),
        )

    def memory_id_for_path(self, path: str) -> str:
        normalized = self.validate_memory_path(path)
        if normalized == "memory/USER.md":
            return "profile_user"
        if normalized == "memory/MEMORY.md":
            return "memory_index"
        if DATE_FILE_RE.match(normalized):
            return f"daily_{Path(normalized).stem.replace('-', '_')}"
        return f"memory_{Path(normalized).stem}"

    def safe_name(self, value: str) -> str:
        cleaned = []
        previous = False
        for char in (value or "").strip():
            if char.isspace() or char in '<>:"/\\|?*':
                if not previous:
                    cleaned.append("_")
                    previous = True
                continue
            if ord(char) < 32:
                continue
            cleaned.append(char)
            previous = False
        return "".join(cleaned).strip("._-").lower()

    def forget_path(self, path: str) -> bool:
        target = self.resolve(path)
        if target.exists() and target.is_file():
            target.unlink()
            return True
        return False
