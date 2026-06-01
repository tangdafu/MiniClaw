import re
from dataclasses import dataclass
from pathlib import Path

from ..types import Tool


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: Path
    skill_md: Path


class SkillRepository:
    def __init__(self, skills_dir: Path | str | None = None):
        if skills_dir is None:
            self.skills_dir = Path(__file__).parents[2] / "skills"
        else:
            self.skills_dir = Path(skills_dir)
        self._skills_by_name: dict[str, SkillInfo] | None = None

    def list_skills(self) -> list[dict]:
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "path": str(skill.skill_md),
            }
            for skill in self._get_index().values()
        ]

    def read_skill_list(self) -> str:
        skills = self.list_skills()
        if not skills:
            return "暂无可用 skill"

        lines = ["可用技能列表："]
        for skill in skills:
            lines.append(f"- {skill['name']}: {skill['description']}")

        return "\n".join(lines)

    def read_skill(self, skill_name: str, file_path: str = "SKILL.md") -> str:
        if not self.skills_dir.exists():
            return "[错误] skills 目录不存在"

        skill = self._get_index().get(skill_name)
        if not skill:
            return f"[错误] 未找到 skill: {skill_name}"

        target_file = skill.path / file_path
        try:
            if not target_file.resolve().is_relative_to(skill.path.resolve()):
                return "[错误] 文件路径不合法"
        except (OSError, RuntimeError):
            return "[错误] 文件路径不合法"

        if not target_file.exists():
            return f"[错误] 文件不存在: {file_path}"

        try:
            return target_file.read_text(encoding="utf-8")
        except Exception as exc:
            return f"[错误] 读取文件失败: {exc}"

    def list_skill_files(self, skill_name: str) -> str:
        if not self.skills_dir.exists():
            return "[错误] skills 目录不存在"

        skill = self._get_index().get(skill_name)
        if not skill:
            return f"[错误] 未找到 skill: {skill_name}"

        lines = [f"{skill_name} 目录结构："]
        for file in skill.path.rglob("*"):
            if file.is_file() and not file.name.startswith("."):
                lines.append(f"  - {file.relative_to(skill.path)}")
        return "\n".join(lines)

    def refresh(self) -> None:
        self._skills_by_name = None

    def _get_index(self) -> dict[str, SkillInfo]:
        if self._skills_by_name is None:
            self._skills_by_name = self._build_index()
        return self._skills_by_name

    def _build_index(self) -> dict[str, SkillInfo]:
        if not self.skills_dir.exists():
            return {}

        skills: dict[str, SkillInfo] = {}
        for item in self.skills_dir.iterdir():
            if not item.is_dir() or item.name.startswith(".") or item.name == "refs":
                continue

            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                continue

            meta = self._parse_frontmatter(skill_md)
            if not meta:
                continue

            name = meta.get("name", item.name)
            skills[name] = SkillInfo(
                name=name,
                description=meta.get("description", ""),
                path=item,
                skill_md=skill_md,
            )

        return skills

    @staticmethod
    def _parse_frontmatter(skill_md_path: Path) -> dict | None:
        try:
            text = skill_md_path.read_text(encoding="utf-8")
            match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
            if not match:
                return None

            frontmatter = match.group(1)
            meta = {}
            for line in frontmatter.strip().split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip().strip('"').strip("'")

            return meta
        except Exception:
            return None


def get_skill_tools(repository: SkillRepository) -> list[Tool]:
    return [
        Tool(
            name="read_skill_list",
            description="读取所有可用 skill 的列表，返回每个 skill 的名称和简介。当用户需要完成特定任务（如生成PPT、处理Excel、格式化文档等）时使用此工具查看有哪些 skill 可用。",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=repository.read_skill_list,
        ),
        Tool(
            name="read_skill",
            description="读取指定 skill 目录下的文件内容。默认读取 SKILL.md，也可以读取 skill 目录下的其他文件（如 references/create.md、agents/grader.md、scripts/utils.py 等）。当大模型通过 read_skill_list 选定某个 skill 后，使用此工具读取该 skill 的完整指令和规则。",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "skill 的名称（从 read_skill_list 返回的 name 字段）",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "相对于 skill 目录的文件路径，默认 SKILL.md。例如：references/create.md、agents/grader.md、scripts/utils.py",
                    },
                },
                "required": ["skill_name"],
            },
            handler=repository.read_skill,
        ),
        Tool(
            name="list_skill_files",
            description="列出指定 skill 目录下的所有文件结构。当需要了解某个 skill 包含哪些子文件（references、agents、scripts 等）时使用。",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "skill 的名称（从 read_skill_list 返回的 name 字段）",
                    }
                },
                "required": ["skill_name"],
            },
            handler=repository.list_skill_files,
        ),
    ]
