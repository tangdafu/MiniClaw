"""MiniClaw Agent - 纯 Agent Loop"""

import os
import json
import inspect
import logging
from typing import AsyncIterator

from openai import AsyncOpenAI

from .types import Tool, Event

logger = logging.getLogger(__name__)


class ToolCallParser:
    """工具调用增量解析器"""

    def __init__(self):
        self.tool_calls: list[dict] = []

    def feed(self, tc_delta) -> None:
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
        return self.tool_calls

    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


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
    纯 Agent Loop — 只负责 LLM 调用和工具执行

    输入: messages (完整对话历史)
    输出: Event 流 (text / reasoning / tool_call / tool_result / done / error)
    """

    def __init__(self, config: AgentConfig, tools: list[Tool] | None = None):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.max_iterations = config.max_iterations
        self.system_prompt = config.system_prompt
        self.tools: list[Tool] = tools or []
        self.tool_map: dict[str, Tool] = {t.name: t for t in self.tools}

    def _build_messages(self, messages: list[dict]) -> list[dict]:
        """构建消息列表，注入系统提示，并清理 API 不兼容字段"""
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        for msg in messages:
            # 复制消息，避免修改原始历史
            clean_msg = dict(msg)
            # 移除空的 reasoning_content，避免部分 OpenAI 兼容 API 报错
            if clean_msg.get("reasoning_content") == "":
                clean_msg.pop("reasoning_content", None)
            result.append(clean_msg)
        return result

    def _get_tool_schemas(self) -> list[dict] | None:
        if not self.tools:
            return None
        return [t.to_openai_schema() for t in self.tools]

    async def _execute_tool(self, tool_name: str, arguments: dict) -> str:
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

    async def chat(self, messages: list[dict], user_message: str) -> AsyncIterator[Event]:
        """
        Agent Loop — 流式对话，自动处理工具调用

        职责：
        1. 将 user_message 追加到 messages（原地修改）
        2. 与 LLM 进行多轮对话，自动执行工具
        3. 将 assistant 消息（含 tool_calls）和 tool 结果追加到 messages
        4. 返回 Event 流

        Args:
            messages: 当前会话历史列表（会被原地修改，调用结束后包含完整历史）
            user_message: 用户最新输入

        Yields:
            Event: 流式事件
        """
        # 追加用户消息到历史
        messages.append({"role": "user", "content": user_message})

        iteration = 0

        try:
            while iteration < self.max_iterations:
                iteration += 1

                # 构建给 LLM 的消息（注入 system_prompt，过滤不兼容字段）
                current_messages = self._build_messages(messages)

                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=current_messages,
                    tools=self._get_tool_schemas(),
                    tool_choice="auto" if self.tools else None,
                    stream=True,
                )

                assistant_message: dict = {"role": "assistant", "content": "", "reasoning_content": ""}
                parser = ToolCallParser()

                async for chunk in response:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    if getattr(delta, "reasoning_content", None):
                        assistant_message["reasoning_content"] += delta.reasoning_content
                        yield Event.reasoning(delta.reasoning_content)

                    if delta.content:
                        assistant_message["content"] += delta.content
                        yield Event.text(delta.content)

                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            parser.feed(tc)

                # 将 assistant 消息（含可能的 tool_calls）追加到原始历史
                messages.append(assistant_message)

                if not parser.has_tool_calls():
                    yield Event.done()
                    return

                for tc in parser.get_tool_calls():
                    tool_name = tc["function"]["name"]
                    tool_args = json.loads(tc["function"]["arguments"])

                    yield Event.tool_call(tool_name, json.dumps(tool_args, ensure_ascii=False))

                    result = await self._execute_tool(tool_name, tool_args)

                    yield Event.tool_result(tool_name, result)

                    # 将 tool 结果追加到原始历史
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

            yield Event.text("\n\n[达到最大迭代次数，对话结束]")
            yield Event.done()

        except Exception as e:
            logger.exception("Chat loop error")
            yield Event.error(str(e))
