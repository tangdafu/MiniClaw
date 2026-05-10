"""工具定义 - 基础工具集"""

import os
import re
import subprocess
from pathlib import Path

from miniclaw import Tool


class SkillManager:
    """Skill 管理器"""

    def __init__(self, skills_dir: Path | str | None = None):
        if skills_dir is None:
            # 默认：backend/skills/
            self.skills_dir = Path(__file__).parent / "skills"
        else:
            self.skills_dir = Path(skills_dir)

    def list_skills(self) -> list[dict]:
        """列出所有 skill，返回结构化数据"""
        if not self.skills_dir.exists():
            return []

        skills = []
        for item in self.skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.') and item.name != 'refs':
                skill_md = item / "SKILL.md"
                if skill_md.exists():
                    meta = self._parse_frontmatter(skill_md)
                    if meta:
                        skills.append({
                            "name": meta.get("name", item.name),
                            "description": meta.get("description", ""),
                            "path": str(skill_md),
                        })

        return skills

    def read_skill_list(self) -> str:
        """读取 skill 列表，返回格式化字符串（给 LLM 使用）"""
        skills = self.list_skills()
        if not skills:
            return "暂无可用 skill"

        lines = ["可用技能列表："]
        for s in skills:
            lines.append(f"- {s['name']}: {s['description']}")

        return "\n".join(lines)

    def read_skill(self, skill_name: str, file_path: str = "SKILL.md") -> str:
        """
        读取指定 skill 目录下的文件内容。
        默认读取 SKILL.md，也可以读取 skill 目录下的其他文件（如 references/create.md、agents/grader.md 等）。
        """
        if not self.skills_dir.exists():
            return "[错误] skills 目录不存在"

        # 按名称查找 skill 目录
        for item in self.skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                skill_md = item / "SKILL.md"
                if skill_md.exists():
                    meta = self._parse_frontmatter(skill_md)
                    if meta and meta.get("name") == skill_name:
                        target_file = item / file_path
                        # 安全检查：确保文件在 skill 目录内
                        try:
                            target_file.resolve().relative_to(item.resolve())
                        except ValueError:
                            return "[错误] 文件路径不合法"

                        if not target_file.exists():
                            return f"[错误] 文件不存在: {file_path}"

                        try:
                            return target_file.read_text(encoding="utf-8")
                        except Exception as e:
                            return f"[错误] 读取文件失败: {e}"

        return f"[错误] 未找到 skill: {skill_name}"

    def list_skill_files(self, skill_name: str) -> str:
        """列出指定 skill 目录下的所有文件结构"""
        if not self.skills_dir.exists():
            return "[错误] skills 目录不存在"

        for item in self.skills_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                skill_md = item / "SKILL.md"
                if skill_md.exists():
                    meta = self._parse_frontmatter(skill_md)
                    if meta and meta.get("name") == skill_name:
                        lines = [f"{skill_name} 目录结构："]
                        for f in item.rglob("*"):
                            if f.is_file() and not f.name.startswith('.'):
                                rel = f.relative_to(item)
                                lines.append(f"  - {rel}")
                        return "\n".join(lines)

        return f"[错误] 未找到 skill: {skill_name}"

    @staticmethod
    def _parse_frontmatter(skill_md_path: Path) -> dict | None:
        """只解析 SKILL.md 的 frontmatter"""
        try:
            text = skill_md_path.read_text(encoding="utf-8")
            match = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
            if not match:
                return None

            frontmatter = match.group(1)
            meta = {}
            for line in frontmatter.strip().split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    meta[key.strip()] = value.strip().strip('"').strip("'")

            return meta
        except Exception:
            return None


async def execute_command(command: str, workdir: str | None = None) -> str:
    """在本地终端执行一条命令并返回输出结果。"""
    try:
        cwd = workdir or os.getcwd()
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            cwd=cwd,
            timeout=30
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "[错误] 命令执行超时（30秒）"
    except Exception as e:
        return f"[错误] {e}"


def get_tools(skills_dir: Path | str | None = None) -> list[Tool]:
    """返回所有可用工具"""
    skill_manager = SkillManager(skills_dir)

    return [
        Tool(
            name="read_skill_list",
            description="读取所有可用 skill 的列表，返回每个 skill 的名称和简介。当用户需要完成特定任务（如生成PPT、处理Excel、格式化文档等）时使用此工具查看有哪些 skill 可用。",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            handler=skill_manager.read_skill_list,
        ),
        Tool(
            name="read_skill",
            description="读取指定 skill 目录下的文件内容。默认读取 SKILL.md，也可以读取 skill 目录下的其他文件（如 references/create.md、agents/grader.md、scripts/utils.py 等）。当大模型通过 read_skill_list 选定某个 skill 后，使用此工具读取该 skill 的完整指令和规则。",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "skill 的名称（从 read_skill_list 返回的 name 字段）"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "相对于 skill 目录的文件路径，默认 SKILL.md。例如：references/create.md、agents/grader.md、scripts/utils.py"
                    }
                },
                "required": ["skill_name"]
            },
            handler=skill_manager.read_skill,
        ),
        Tool(
            name="list_skill_files",
            description="列出指定 skill 目录下的所有文件结构。当需要了解某个 skill 包含哪些子文件（references、agents、scripts 等）时使用。",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "skill 的名称（从 read_skill_list 返回的 name 字段）"
                    }
                },
                "required": ["skill_name"]
            },
            handler=skill_manager.list_skill_files,
        ),
        Tool(
            name="execute_command",
            description="在本地终端执行一条命令并返回输出结果。可用于运行代码、查看文件、安装包等。",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令"
                    },
                    "workdir": {
                        "type": "string",
                        "description": "工作目录（可选，默认当前目录）"
                    }
                },
                "required": ["command"]
            },
            handler=execute_command,
        ),
    ]
