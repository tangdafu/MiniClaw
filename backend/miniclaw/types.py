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
        # 只在有实际内容时才发送 reasoning_content，避免部分 API 报错
        if self.reasoning_content:
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
    type: Literal["text", "reasoning", "tool_call", "tool_result", "done", "error", "session_created", "context_compression", "context_usage", "context_pruning"]
    content: str = ""
    name: str = ""           # 工具名称
    arguments: str = ""      # 工具参数
    result: str = ""         # 工具结果
    error_msg: str = ""      # 错误信息（字段名避免和静态方法冲突）
    session_id: str = ""     # 会话 ID（用于 session_created 事件）
    stage: str = ""
    reason: str = ""
    detail: str = ""
    estimated_tokens: int | None = None
    trigger_tokens: int | None = None
    target_tokens: int | None = None
    head_messages: int | None = None
    tail_messages: int | None = None
    covered_messages: int | None = None
    summary_tokens: int | None = None
    estimated_tokens_after: int | None = None
    model_messages: int | None = None
    history_messages: int | None = None
    compacted: bool | None = None
    cache_hit: bool | None = None
    system_tokens: int | None = None
    summary_tokens_breakdown: int | None = None
    user_tokens: int | None = None
    assistant_tokens: int | None = None
    tool_tokens: int | None = None
    prune_id: str = ""
    tool_name: str = ""
    tool_call_id: str = ""
    original_tokens: int | None = None
    retained_tokens: int | None = None
    omitted_tokens: int | None = None
    message_index: int | None = None

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
        return Event(type="session_created", session_id=session_id)

    @staticmethod
    def context_compression(**kwargs) -> "Event":
        return Event(type="context_compression", **kwargs)

    @staticmethod
    def context_usage(**kwargs) -> "Event":
        return Event(type="context_usage", **kwargs)

    @staticmethod
    def context_pruning(**kwargs) -> "Event":
        return Event(type="context_pruning", **kwargs)

    def model_dump(self, **kwargs) -> dict:
        """自定义序列化，将 error_msg 映射为 error 键"""
        d = super().model_dump(**kwargs)
        # 对外暴露时，将 error_msg 映射为 error
        if "error_msg" in d:
            d["error"] = d.pop("error_msg")
        return d
