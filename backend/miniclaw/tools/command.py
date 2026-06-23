import locale
import os
import re
import subprocess

from ..react_context import ToolExecutionContext
from ..types import Tool


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class CommandRunner:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    async def run(self, command: str, workdir: str | None = None, context: ToolExecutionContext | None = None) -> str:
        validation_error = self.validate(command, workdir)
        if validation_error:
            return validation_error

        if context is not None:
            trace = dict(context.trace)
            commands = list(trace.get("commands", []))
            commands.append({"command": command, "workdir": workdir or os.getcwd()})
            trace["commands"] = commands
            context.trace.clear()
            context.trace.update(trace)

        try:
            cwd = workdir or os.getcwd()
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                cwd=cwd,
                timeout=self.timeout,
            )
            output = ""
            if result.stdout:
                output += self.decode_output(result.stdout)
            if result.stderr:
                output += f"[stderr]\n{self.decode_output(result.stderr)}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"[错误] 命令执行超时（{self.timeout}秒）"
        except Exception as exc:
            return f"[错误] {exc}"

    def validate(self, command: str, workdir: str | None = None) -> str | None:
        return None

    def decode_output(self, output: bytes) -> str:
        encodings = ["utf-8", locale.getpreferredencoding(False), "gbk", "mbcs"]
        for encoding in dict.fromkeys(encodings):
            try:
                text = output.decode(encoding)
                return ANSI_ESCAPE_RE.sub("", text)
            except (LookupError, UnicodeDecodeError):
                continue
        return ANSI_ESCAPE_RE.sub("", output.decode("utf-8", errors="replace"))


def get_command_tools(runner: CommandRunner) -> list[Tool]:
    return [
        Tool(
            name="execute_command",
            description="在本地终端执行一条命令并返回输出结果。可用于运行代码、查看文件、安装包等。",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的命令",
                    },
                    "workdir": {
                        "type": "string",
                        "description": "工作目录（可选，默认当前目录）",
                    },
                },
                "required": ["command"],
            },
            handler=runner.run,
            category="command",
            risk_level="high",
            execution_policy="confirm",
        ),
    ]
