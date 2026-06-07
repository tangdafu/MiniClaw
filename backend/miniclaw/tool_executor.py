import inspect
import json
import logging
from typing import Any

from .react_context import ToolExecution, ToolExecutionContext
from .types import Tool

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(self, tools: list[Tool] | None = None):
        self.tools = tools or []
        self.tool_map: dict[str, Tool] = {tool.name: tool for tool in self.tools}

    async def execute(self, tool_call: dict, context: ToolExecutionContext | None = None) -> ToolExecution:
        context = context or ToolExecutionContext()
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
                session_id=context.session_id,
                run_id=context.run_id,
            )

        if not isinstance(arguments, dict):
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments={},
                result="[错误] 工具参数必须是 JSON 对象",
                error="tool arguments must be an object",
                session_id=context.session_id,
                run_id=context.run_id,
            )

        tool = self.tool_map.get(tool_name)
        if not tool:
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments=arguments,
                result=f"[错误] 未知工具: {tool_name}",
                error="unknown tool",
                session_id=context.session_id,
                run_id=context.run_id,
            )

        try:
            result = await self._call_handler(tool, arguments, context)
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments=arguments,
                result=str(result),
                session_id=context.session_id,
                run_id=context.run_id,
            )
        except Exception as exc:
            logger.exception("Tool execution failed: %s", tool_name)
            return ToolExecution(
                tool_call_id=tool_call_id,
                name=tool_name,
                arguments=arguments,
                result=f"[错误] 执行工具失败: {exc}",
                error=str(exc),
                session_id=context.session_id,
                run_id=context.run_id,
            )

    async def _call_handler(self, tool: Tool, arguments: dict[str, Any], context: ToolExecutionContext) -> Any:
        handler = tool.handler
        call_arguments = dict(arguments)
        signature = inspect.signature(handler)
        if "context" in signature.parameters:
            call_arguments["context"] = context
        elif "tool_context" in signature.parameters:
            call_arguments["tool_context"] = context
        if inspect.iscoroutinefunction(handler):
            return await handler(**call_arguments)
        return handler(**call_arguments)
