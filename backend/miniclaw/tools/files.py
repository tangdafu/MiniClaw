import fnmatch
import re
from pathlib import Path

from ..types import Tool


class FileTools:
    def __init__(self, base_dir: Path | str | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()

    def read_file(self, path: str, max_lines: int = 2000) -> str:
        target = self._resolve(path)
        if not target.exists():
            return f"[错误] 文件不存在: {path}"
        if not target.is_file():
            return f"[错误] 不是文件: {path}"

        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as exc:
            return f"[错误] 读取文件失败: {exc}"

        limit = self._positive_limit(max_lines, 2000)
        selected = lines[:limit]
        output = "\n".join(f"{index}: {line}" for index, line in enumerate(selected, start=1))
        if len(lines) > limit:
            output += f"\n[truncated: showing {limit} of {len(lines)} lines]"
        return output or "(empty file)"

    def list_files(self, pattern: str = "**/*", max_results: int = 200) -> str:
        limit = self._positive_limit(max_results, 200)
        matches: list[str] = []

        root = self.base_dir
        for path in root.glob(pattern):
            if path.is_file():
                matches.append(str(path.relative_to(root)))

        matches.sort()
        if not matches:
            return "未找到匹配文件"

        selected = matches[:limit]
        output = "\n".join(selected)
        if len(matches) > limit:
            output += f"\n[truncated: showing {limit} of {len(matches)} files]"
        return output

    def search_text(
        self,
        pattern: str,
        file_pattern: str = "**/*",
        max_results: int = 100,
        regex: bool = False,
    ) -> str:
        limit = self._positive_limit(max_results, 100)
        results: list[str] = []
        matcher = re.compile(pattern) if regex else None

        for path in sorted(self.base_dir.glob(file_pattern)):
            if not path.is_file() or self._is_probably_binary(path):
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for line_number, line in enumerate(lines, start=1):
                matched = bool(matcher.search(line)) if matcher else pattern in line
                if not matched:
                    continue

                rel_path = path.relative_to(self.base_dir)
                results.append(f"{rel_path}:{line_number}: {line}")
                if len(results) >= limit:
                    return "\n".join(results) + f"\n[truncated: showing first {limit} matches]"

        if not results:
            return "未找到匹配内容"
        return "\n".join(results)

    def write_file(self, path: str, content: str) -> str:
        target = self._resolve(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except Exception as exc:
            return f"[错误] 写入文件失败: {exc}"
        return f"已写入文件: {path}"

    def replace_text(self, path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        target = self._resolve(path)
        if not target.exists():
            return f"[错误] 文件不存在: {path}"
        if not target.is_file():
            return f"[错误] 不是文件: {path}"

        try:
            content = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"[错误] 读取文件失败: {exc}"

        count = content.count(old_text)
        if count == 0:
            return "[错误] 未找到要替换的文本"
        if count > 1 and not replace_all:
            return f"[错误] 找到 {count} 处匹配，请设置 replace_all=true 或提供更精确的 old_text"

        updated = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
        try:
            target.write_text(updated, encoding="utf-8")
        except Exception as exc:
            return f"[错误] 写入文件失败: {exc}"

        replaced = count if replace_all else 1
        return f"已替换 {replaced} 处文本: {path}"

    def _resolve(self, path: str) -> Path:
        target = Path(path)
        if target.is_absolute():
            return target
        return self.base_dir / target

    def _positive_limit(self, value: int, default: int) -> int:
        try:
            limit = int(value)
        except (TypeError, ValueError):
            return default
        return limit if limit > 0 else default

    def _is_probably_binary(self, path: Path) -> bool:
        try:
            chunk = path.read_bytes()[:1024]
        except Exception:
            return True
        return b"\0" in chunk


def get_file_tools(file_tools: FileTools) -> list[Tool]:
    return [
        Tool(
            name="read_file",
            description="读取本地文本文件内容，按行号返回。支持 max_lines 限制输出行数。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要读取的文件路径"},
                    "max_lines": {"type": "integer", "description": "最多返回的行数，默认 2000"},
                },
                "required": ["path"],
            },
            handler=file_tools.read_file,
        ),
        Tool(
            name="list_files",
            description="按 glob 模式列出本地文件路径。默认模式为 **/*。",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob 匹配模式，默认 **/*"},
                    "max_results": {"type": "integer", "description": "最多返回的文件数量，默认 200"},
                },
                "required": [],
            },
            handler=file_tools.list_files,
        ),
        Tool(
            name="search_text",
            description="在本地文本文件中搜索字符串或正则表达式，返回文件路径、行号和匹配行。",
            parameters={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "要搜索的字符串或正则表达式"},
                    "file_pattern": {"type": "string", "description": "文件 glob 范围，默认 **/*"},
                    "max_results": {"type": "integer", "description": "最多返回的匹配数量，默认 100"},
                    "regex": {"type": "boolean", "description": "是否按正则表达式搜索，默认 false"},
                },
                "required": ["pattern"],
            },
            handler=file_tools.search_text,
        ),
        Tool(
            name="write_file",
            description="写入本地文本文件，会创建缺失的父目录并覆盖已有文件内容。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要写入的文件路径"},
                    "content": {"type": "string", "description": "要写入的完整文本内容"},
                },
                "required": ["path", "content"],
            },
            handler=file_tools.write_file,
        ),
        Tool(
            name="replace_text",
            description="在本地文本文件中执行精确文本替换。默认只替换一处；多处匹配时需设置 replace_all=true。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要修改的文件路径"},
                    "old_text": {"type": "string", "description": "要被替换的精确旧文本"},
                    "new_text": {"type": "string", "description": "替换后的新文本"},
                    "replace_all": {"type": "boolean", "description": "是否替换所有匹配，默认 false"},
                },
                "required": ["path", "old_text", "new_text"],
            },
            handler=file_tools.replace_text,
        ),
    ]
