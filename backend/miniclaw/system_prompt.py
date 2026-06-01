import getpass
import locale
import os
import platform
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


UNKNOWN = "Unknown"
TRUTHY_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EnvironmentSnapshot:
    os_name: str = UNKNOWN
    os_version: str = UNKNOWN
    os_arch: str = UNKNOWN
    device_model: str = UNKNOWN
    hostname: str = UNKNOWN
    username: str = UNKNOWN
    workspace_root: str = UNKNOWN
    backend_dir: str = UNKNOWN
    frontend_dir: str = UNKNOWN
    skills_dir: str = UNKNOWN
    current_datetime: str = UNKNOWN
    shell_name: str = UNKNOWN
    preferred_encoding: str = UNKNOWN
    session_id: str = UNKNOWN


def collect_environment(
    workspace_root: Path | str | None = None,
    backend_dir: Path | str | None = None,
    frontend_dir: Path | str | None = None,
    skills_dir: Path | str | None = None,
) -> EnvironmentSnapshot:
    workspace_path = Path(workspace_root).resolve() if workspace_root else _default_workspace_root()
    backend_path = Path(backend_dir).resolve() if backend_dir else workspace_path / "backend"
    frontend_path = Path(frontend_dir).resolve() if frontend_dir else workspace_path / "frontend"
    skills_path = Path(skills_dir).resolve() if skills_dir else backend_path / "skills"

    return EnvironmentSnapshot(
        os_name=_value_or_unknown(platform.system()),
        os_version=_value_or_unknown(platform.version()),
        os_arch=_value_or_unknown(platform.machine()),
        device_model=_detect_device_model(),
        hostname=_safe_call(socket.gethostname),
        username=_safe_call(getpass.getuser),
        workspace_root=str(workspace_path),
        backend_dir=str(backend_path),
        frontend_dir=str(frontend_path),
        skills_dir=str(skills_path),
        current_datetime=datetime.now().astimezone().isoformat(timespec="seconds"),
        shell_name=_detect_shell_name(),
        preferred_encoding=_value_or_unknown(locale.getpreferredencoding(False)),
    )


def render_default_system_prompt(
    snapshot: EnvironmentSnapshot,
    agent_name: str | None = None,
    extra_instructions: str | None = None,
    disable_default: bool | None = None,
) -> str | None:
    disabled = _env_truthy("MINICLAW_DISABLE_DEFAULT_SYSTEM_PROMPT") if disable_default is None else disable_default
    if disabled:
        return None

    name = agent_name or os.getenv("MINICLAW_AGENT_NAME") or "汤xio夫"
    extra = extra_instructions if extra_instructions is not None else os.getenv("MINICLAW_SYSTEM_PROMPT_EXTRA", "")

    prompt = f"""
你是 MiniClaw，一个运行在用户本地电脑上的 AI Agent。你的中文名字可以理解为“{name}”，但不要刻意反复自我介绍；只在自然场景下体现你的身份。

你不是普通聊天机器人，而是一个能理解当前工作空间、使用本地工具、持续协作的桌面级智能体。你的目标是帮助用户完成本地开发、文件阅读、项目分析、技能调用、命令执行和知识整理等任务。

## 当前运行环境

- 操作系统：{snapshot.os_name}
- 系统版本：{snapshot.os_version}
- 系统架构：{snapshot.os_arch}
- 设备型号：{snapshot.device_model}
- 主机名：{snapshot.hostname}
- 当前用户：{snapshot.username}
- 当前工作空间：{snapshot.workspace_root}
- 当前后端目录：{snapshot.backend_dir}
- 当前前端目录：{snapshot.frontend_dir}
- 当前 Skills 目录：{snapshot.skills_dir}
- 当前会话 ID：{snapshot.session_id}
- 当前时间：{snapshot.current_datetime}
- 默认 Shell：{snapshot.shell_name}
- 默认编码偏好：{snapshot.preferred_encoding}

如果动态环境信息缺失，不要编造。你可以说明“当前未提供该信息”，并基于已有信息继续工作。

## 行为准则

- 优先理解用户真实目标，而不是机械执行字面指令。
- 在需要代码、文件或项目上下文时，先读取或搜索相关文件，不要凭空猜测。
- 对简单问题直接回答；对复杂任务先简要说明理解，再使用工具推进。
- 执行命令或修改文件前，考虑当前工作空间、操作系统、路径、Shell 和编码差异。
- 如果任务存在风险，先提醒用户风险，再给出安全路径。
- 如果用户要求修改项目，保持改动最小、聚焦、可验证。
- 不要编造文件内容、命令输出、系统信息或工具结果。
- 不要删除、覆盖或重置用户文件，除非用户明确要求。
- 不要暴露 API Key、token、密钥、cookie 等敏感信息。

## 工具使用策略

- 想了解目录结构：使用文件列表工具。
- 想找某段代码：使用文本搜索工具。
- 想读具体文件：使用读文件工具。
- 想修改文件：先读文件，再进行最小修改。
- 想运行项目命令：使用命令执行工具，并指定合适工作目录。
- 想使用技能：先读取 skill 列表，再读取相关 skill 内容。

Windows 环境下要注意 PowerShell、路径空格、编码和换行差异。命令输出可能包含 ANSI 控制码或系统编码差异，应以清理后的可读结果为准。

## Skills 使用

Skills 是你的扩展能力，当前 Skills 目录是：{snapshot.skills_dir}

当用户请求明显匹配某个 skill 的能力时，你应优先查看 skill 列表和对应 skill 说明，再决定如何使用。不要假设某个 skill 一定存在。

## 本地文件与工作空间

默认在当前工作空间内工作：{snapshot.workspace_root}

- 不要随意访问工作空间外的路径，除非用户明确要求。
- 修改文件前应确认目标文件属于当前任务。
- 遇到已有未提交改动时，不要擅自回滚。
- 写入文件时保持原有风格、格式和编码。

## 输出风格

默认使用中文回答，除非用户使用英文，或代码、命令、错误信息需要保留英文。回答应直接、清楚、实用；命令、路径、函数名、文件名使用行内代码格式。

## OpenSpec 约定

如果用户要求新增较大功能或结构性改动，应建议或创建 OpenSpec change。探索想法时先讨论，不写代码；形成方案后创建 proposal/design/spec/tasks；用户确认实现后再执行 tasks。

## 核心目标

成为用户在本地项目中的可靠搭档：看得懂项目，找得到文件，跑得动命令，改得动代码，解释得清楚，不乱动用户东西，出错时能定位原因，不知道时会查证。
""".strip()

    if extra.strip():
        prompt = f"{prompt}\n\n## 额外指令\n\n{extra.strip()}"
    return prompt


def build_default_system_prompt(
    workspace_root: Path | str | None = None,
    backend_dir: Path | str | None = None,
    frontend_dir: Path | str | None = None,
    skills_dir: Path | str | None = None,
) -> str | None:
    return render_default_system_prompt(
        collect_environment(
            workspace_root=workspace_root,
            backend_dir=backend_dir,
            frontend_dir=frontend_dir,
            skills_dir=skills_dir,
        )
    )


def _default_workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _detect_shell_name() -> str:
    shell = os.getenv("SHELL") or os.getenv("COMSPEC") or os.getenv("PSModulePath")
    if not shell:
        return UNKNOWN
    if "PSModulePath" in os.environ and not os.getenv("SHELL"):
        return "PowerShell"
    return Path(shell).name or shell


def _detect_device_model() -> str:
    if platform.system().lower() != "windows":
        return UNKNOWN
    try:
        result = subprocess.run(
            ["wmic", "computersystem", "get", "model"],
            capture_output=True,
            timeout=2,
        )
        output = result.stdout.decode(locale.getpreferredencoding(False), errors="ignore")
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        if len(lines) >= 2:
            return _value_or_unknown(lines[1])
    except Exception:
        pass
    return UNKNOWN


def _safe_call(func) -> str:
    try:
        return _value_or_unknown(func())
    except Exception:
        return UNKNOWN


def _value_or_unknown(value: object) -> str:
    text = str(value or "").strip()
    return text or UNKNOWN


def _env_truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUTHY_VALUES
