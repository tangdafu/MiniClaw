from pathlib import Path

from ..types import Tool
from ..memory import MemoryConfig, MemoryService, get_memory_tools
from .command import CommandRunner, get_command_tools
from .files import FileTools, get_file_tools
from .skills import SkillRepository, get_skill_tools


def get_builtin_tools(skills_dir: Path | str | None = None) -> list[Tool]:
    skill_repository = SkillRepository(skills_dir)
    command_runner = CommandRunner()
    file_tools = FileTools()
    memory_service = MemoryService(MemoryConfig.from_env())

    return [
        *get_skill_tools(skill_repository),
        *get_command_tools(command_runner),
        *get_file_tools(file_tools),
        *get_memory_tools(memory_service),
    ]
