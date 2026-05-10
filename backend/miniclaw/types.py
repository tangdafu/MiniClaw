"""MiniClaw Agent - 核心类型定义"""

from typing import Any, Callable, Literal
from pydantic import BaseModel, Field


class Message(BaseModel):
    """对话消息"""
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None
    tool_calls: list[dict] | None = None
    reasoning_content: str | None = None

    def to_openai_dict(self) -> dict:
        """转换为 OpenAI API 格式"""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.reasoning_content is not None:
            d["reasoning_content"] = self.reasoning_content
        return d


class Tool(BaseModel):
    """工具定义"""
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[..., Any]  # 同步或异步函数

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


class Event(BaseModel):
    """Agent 流式事件"""
    type: Literal["text", "reasoning", "tool_call", "tool_result", "done", "error", "session_created"]
    content: str = ""
    name: str = ""           # 工具名称
    arguments: str = ""      # 工具参数
    result: str = ""         # 工具结果
    error_msg: str = ""      # 错误信息（字段名避免和静态方法冲突）

    @staticmethod
    def text(content: str) -> "Event":
        return Event(type="text", content=content)

    @staticmethod
    def reasoning(content: str) -> "Event":
        return Event(type="reasoning", content=content)

    @staticmethod
    def tool_call(name: str, arguments: str) -> "Event":
        return Event(type="tool_call", name=name, arguments=arguments)

    @staticmethod
    def tool_result(name: str, result: str) -> "Event":
        return Event(type="tool_result", name=name, result=result)

    @staticmethod
    def done() -> "Event":
        return Event(type="done")

    @staticmethod
    def error(message: str) -> "Event":
        return Event(type="error", error_msg=message)

    @staticmethod
    def session_created(session_id: str) -> "Event":
        return Event(type="session_created", content=session_id)

    def model_dump(self, **kwargs) -> dict:
        """自定义序列化，将 error_msg 映射为 error 键"""
        d = super().model_dump(**kwargs)
        # 对外暴露时，将 error_msg 映射为 error
        if "error_msg" in d:
            d["error"] = d.pop("error_msg")
        return d
