"""MiniClaw Agent - 核心 Agent 类"""

import os
import json
import inspect
import logging
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .types import Tool, Event, Message

logger = logging.getLogger(__name__)


class ToolCallParser:
    """工具调用增量解析器"""

    def __init__(self):
        self.tool_calls: list[dict] = []

    def feed(self, tc_delta: Any) -> None:
        """消费一个 tool_call delta 片段"""
        if tc_delta.index is None:
            return

        idx = tc_delta.index
        while len(self.tool_calls) <= idx:
            self.tool_calls.append({
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""}
            })

        if tc_delta.id:
            self.tool_calls[idx]["id"] = tc_delta.id

        func = tc_delta.function
        if func:
            if func.name:
                self.tool_calls[idx]["function"]["name"] = func.name
            if func.arguments:
                self.tool_calls[idx]["function"]["arguments"] += func.arguments

    def get_tool_calls(self) -> list[dict]:
        """获取完整解析后的 tool_calls"""
        return self.tool_calls

    def has_tool_calls(self) -> bool:
        """是否有工具调用"""
        return len(self.tool_calls) > 0

    def reset(self) -> None:
        """重置解析器"""
        self.tool_calls = []


class AgentConfig:
    """Agent 配置"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "gpt-4o",
        max_iterations: int = 20,
        system_prompt: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.model = model
        self.max_iterations = max_iterations
        self.system_prompt = system_prompt


class Agent:
    """
    MiniClaw Agent - 支持工具调用的对话 Agent
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        tools: list[Tool] | None = None,
    ):
        self.config = config or AgentConfig()
        self.client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )
        self.model = self.config.model
        self.max_iterations = self.config.max_iterations
        self.system_prompt = self.config.system_prompt
        self.tools: list[Tool] = tools or []
        self.tool_map: dict[str, Tool] = {t.name: t for t in self.tools}

    def add_tool(self, tool: Tool) -> "Agent":
        """添加工具（支持链式调用）"""
        self.tools.append(tool)
        self.tool_map[tool.name] = tool
        return self

    def _build_messages(self, messages: list[dict]) -> list[Message]:
        """构建消息列表，注入系统提示"""
        result: list[Message] = []

        if self.system_prompt:
            result.append(Message(role="system", content=self.system_prompt))

        for msg in messages:
            result.append(Message(
                role=msg.get("role", "user"),
                content=msg.get("content", ""),
                tool_call_id=msg.get("tool_call_id"),
                tool_calls=msg.get("tool_calls"),
                reasoning_content=msg.get("reasoning_content"),
            ))

        return result

    def _get_tool_schemas(self) -> list[dict] | None:
        """获取 OpenAI 工具 schema"""
        if not self.tools:
            return None
        return [t.to_openai_schema() for t in self.tools]

    async def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """执行工具"""
        tool = self.tool_map.get(tool_name)
        if not tool:
            return f"[错误] 未知工具: {tool_name}"

        try:
            handler = tool.handler
            if inspect.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = handler(**arguments)
            return str(result)
        except Exception as e:
            logger.exception("Tool execution failed: %s", tool_name)
            return f"[错误] 执行工具失败: {e}"

    async def chat(self, messages: list[dict]) -> AsyncIterator[Event]:
        """
        流式对话，自动处理工具调用循环
        """
        current_messages = self._build_messages(messages)
        iteration = 0

        try:
            while iteration < self.max_iterations:
                iteration += 1
                logger.debug("Iteration %d/%d", iteration, self.max_iterations)

                # 调用 LLM
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[m.to_openai_dict() for m in current_messages],
                    tools=self._get_tool_schemas(),
                    tool_choice="auto" if self.tools else None,
                    stream=True,
                )

                assistant_message = Message(role="assistant", content="", reasoning_content="")
                parser = ToolCallParser()

                async for chunk in response:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # 思考内容
                    if getattr(delta, "reasoning_content", None):
                        assistant_message.reasoning_content = (assistant_message.reasoning_content or "") + delta.reasoning_content
                        yield Event.reasoning(delta.reasoning_content)

                    # 文本内容
                    if delta.content:
                        assistant_message.content += delta.content
                        yield Event.text(delta.content)

                    # 工具调用
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            parser.feed(tc)

                # 没有工具调用，对话结束
                if not parser.has_tool_calls():
                    yield Event.done()
                    return

                # 添加 assistant 消息（包含 tool_calls）到历史
                assistant_message.tool_calls = parser.get_tool_calls()
                current_messages.append(assistant_message)

                # 执行工具
                for tc in parser.get_tool_calls():
                    tool_name = tc["function"]["name"]
                    tool_args = json.loads(tc["function"]["arguments"])

                    yield Event.tool_call(tool_name, json.dumps(tool_args, ensure_ascii=False))

                    result = await self._execute_tool(tool_name, tool_args)

                    yield Event.tool_result(tool_name, result)

                    current_messages.append(Message(
                        role="tool",
                        tool_call_id=tc["id"],
                        content=result,
                    ))

            # 达到最大迭代次数
            yield Event.text("\n\n[达到最大迭代次数，对话结束]")
            yield Event.done()

        except Exception as e:
            logger.exception("Chat loop error")
            yield Event.error(str(e))
