import inspect
import json
import logging
from typing import Any

from .react_context import ToolExecution
from .types import Tool

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(self, tools: list[Tool] | None = None):
        self.tools = tools or []
        self.tool_map: dict[str, Tool] = {tool.name: tool for tool in self.tools}

    async def execute(self, tool_call: dict) -> ToolExecution:
        function = tool_call.get("function", {})
        tool_name = function.get("name", "")
        tool_call_id = tool_call.get("id", "")
        arguments_text = function.get("arguments", "") or "{}"

        try:
            arguments = json.loads(arguments_text)
        except json.JSONDecodeError as exc:
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments={},
                result=f"[错误] 工具参数 JSON 解析失败: {exc}",
                error=str(exc),
            )

        if not isinstance(arguments, dict):
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments={},
                result="[错误] 工具参数必须是 JSON 对象",
                error="tool arguments must be an object",
            )

        tool = self.tool_map.get(tool_name)
        if not tool:
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments=arguments,
                result=f"[错误] 未知工具: {tool_name}",
                error="unknown tool",
            )

        try:
            result = await self._call_handler(tool, arguments)
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments=arguments,
                result=str(result),
            )
        except Exception as exc:
            logger.exception("Tool execution failed: %s", tool_name)
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments=arguments,
                result=f"[错误] 执行工具失败: {exc}",
                error=str(exc),
            )

    async def _call_handler(self, tool: Tool, arguments: dict[str, Any]) -> Any:
        handler = tool.handler
        if inspect.iscoroutinefunction(handler):
            return await handler(**arguments)
        return handler(**arguments)
