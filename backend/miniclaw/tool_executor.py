import inspect
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .react_context import ToolExecution, ToolExecutionContext
from .types import Tool, ToolGovernanceDecision


@dataclass(frozen=True)
class PreparedToolCall:
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    arguments_text: str
    tool: Tool | None
    decision: ToolGovernanceDecision
    started_at: str
    error: str | None = None

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ToolExecutor:
    def __init__(self, tools: list[Tool] | None = None):
        self.tools = tools or []
        self.tool_map: dict[str, Tool] = {tool.name: tool for tool in self.tools}

    async def execute(self, tool_call: dict, context: ToolExecutionContext | None = None) -> ToolExecution:
        prepared = self.prepare(tool_call, context=context)
        if prepared.tool is None or prepared.decision.action != "allow":
            return self._prepared_to_execution(prepared, context or ToolExecutionContext())
        return await self.execute_prepared(prepared, context=context)

    def prepare(self, tool_call: dict, context: ToolExecutionContext | None = None) -> PreparedToolCall:
        context = context or ToolExecutionContext()
        function = tool_call.get("function", {})
        tool_name = function.get("name", "")
        tool_call_id = tool_call.get("id", "")
        arguments_text = function.get("arguments", "") or "{}"
        started_at = utc_now_iso()

        try:
            arguments = json.loads(arguments_text)
        except json.JSONDecodeError as exc:
            return PreparedToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments={},
                arguments_text=arguments_text,
                tool=None,
                decision=ToolGovernanceDecision(action="deny", reason="invalid_json_arguments"),
                started_at=started_at,
                error=str(exc),
            )

        if not isinstance(arguments, dict):
            return PreparedToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments={},
                arguments_text=arguments_text,
                tool=None,
                decision=ToolGovernanceDecision(action="deny", reason="invalid_arguments_shape"),
                started_at=started_at,
                error="tool arguments must be an object",
            )

        tool = self.tool_map.get(tool_name)
        if not tool:
            return PreparedToolCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments=arguments,
                arguments_text=arguments_text,
                tool=None,
                decision=ToolGovernanceDecision(action="deny", reason="unknown_tool"),
                started_at=started_at,
                error="unknown tool",
            )

        return PreparedToolCall(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            arguments_text=arguments_text,
            tool=tool,
            decision=self._govern(tool),
            started_at=started_at,
        )

    async def execute_prepared(
        self,
        prepared: PreparedToolCall,
        context: ToolExecutionContext | None = None,
        force_allow: bool = False,
    ) -> ToolExecution:
        context = context or ToolExecutionContext()
        if prepared.tool is None or (prepared.decision.action != "allow" and not force_allow):
            return self._prepared_to_execution(prepared, context)

        decision = "allow" if force_allow else prepared.decision.action

        try:
            result = await self._call_handler(prepared.tool, prepared.arguments, context)
            changed_files = self._extract_changed_files(context)
            return ToolExecution(
                tool_call_id=prepared.tool_call_id,
                name=prepared.tool_name,
                arguments=prepared.arguments,
                result=str(result),
                session_id=context.session_id,
                run_id=context.run_id,
                started_at=prepared.started_at,
                finished_at=utc_now_iso(),
                decision=decision,
                changed_files=changed_files,
            )
        except Exception as exc:
            logger.exception("Tool execution failed: %s", prepared.tool_name)
            return ToolExecution(
                tool_call_id=prepared.tool_call_id,
                name=prepared.tool_name,
                arguments=prepared.arguments,
                result=f"[错误] 执行工具失败: {exc}",
                error=str(exc),
                session_id=context.session_id,
                run_id=context.run_id,
                started_at=prepared.started_at,
                finished_at=utc_now_iso(),
                decision=decision,
            )

    def _prepared_to_execution(self, prepared: PreparedToolCall, context: ToolExecutionContext) -> ToolExecution:
        if prepared.decision.reason == "invalid_json_arguments":
            result = f"[错误] 工具参数 JSON 解析失败: {prepared.error}"
        elif prepared.decision.reason == "invalid_arguments_shape":
            result = "[错误] 工具参数必须是 JSON 对象"
        elif prepared.decision.reason == "unknown_tool":
            result = f"[错误] 未知工具: {prepared.tool_name}"
        elif prepared.tool is not None:
            result = self._blocked_result(prepared.tool, prepared.decision)
        else:
            result = "[错误] 工具执行被阻止"
        return ToolExecution(
            tool_call_id=prepared.tool_call_id,
            name=prepared.tool_name,
            arguments=prepared.arguments,
            result=result,
            error=prepared.error or prepared.decision.reason,
            session_id=context.session_id,
            run_id=context.run_id,
            started_at=prepared.started_at,
            finished_at=utc_now_iso(),
            decision=prepared.decision.action,
            blocked_reason=prepared.decision.reason,
        )

    def _govern(self, tool: Tool) -> ToolGovernanceDecision:
        if tool.visibility == "internal":
            return ToolGovernanceDecision(action="deny", reason="internal_tool", policy="visibility")
        if tool.risk_level == "high":
            return ToolGovernanceDecision(action="deny", reason="high_risk_tool", policy="risk_level")
        if tool.execution_policy == "confirm":
            return ToolGovernanceDecision(action="confirm", reason="confirmation_required", policy="execution_policy")
        return ToolGovernanceDecision(action="allow", policy="default")

    def _blocked_result(self, tool: Tool, decision: ToolGovernanceDecision) -> str:
        if decision.action == "confirm":
            return f"[已阻止] 工具 {tool.name} 需要确认后才能执行"
        return f"[已阻止] 工具 {tool.name} 因治理策略未执行"

    def _extract_changed_files(self, context: ToolExecutionContext) -> list[str]:
        changed_files = context.trace.get("changed_files", [])
        if not isinstance(changed_files, list):
            return []
        return [str(path) for path in changed_files]

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
