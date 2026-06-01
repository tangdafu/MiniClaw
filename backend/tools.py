"""Compatibility entry point for MiniClaw built-in tools."""

from pathlib import Path

from miniclaw import Tool
from miniclaw.tools import CommandRunner, SkillRepository, get_builtin_tools

SkillManager = SkillRepository


async def execute_command(command: str, workdir: str | None = None) -> str:
    return await CommandRunner().run(command, workdir)


def get_tools(skills_dir: Path | str | None = None) -> list[Tool]:
    return get_builtin_tools(skills_dir=skills_dir)
