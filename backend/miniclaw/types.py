"""MiniClaw Agent - 核心类型定义"""

from typing import Any, Callable, ClassVar, Literal
from pydantic import BaseModel, ConfigDict, Field, model_serializer


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
    category: str = "general"
    risk_level: Literal["low", "medium", "high"] = "low"
    visibility: Literal["model", "internal"] = "model"
    execution_policy: str = "auto"

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

    model_config = ConfigDict(extra="forbid")

    type: Literal["text", "reasoning", "tool_call", "tool_result", "done", "error", "session_created", "context_compression", "context_usage", "context_pruning"]
    data: dict[str, Any] = Field(default_factory=dict)

    _default_values: ClassVar[dict[str, Any]] = {
        "content": "",
        "name": "",
        "arguments": "",
        "result": "",
        "error_msg": "",
        "session_id": "",
        "stage": "",
        "reason": "",
        "detail": "",
        "prune_id": "",
        "tool_name": "",
        "tool_call_id": "",
        "estimated_tokens": None,
        "trigger_tokens": None,
        "target_tokens": None,
        "head_messages": None,
        "tail_messages": None,
        "covered_messages": None,
        "summary_tokens": None,
        "estimated_tokens_after": None,
        "model_messages": None,
        "history_messages": None,
        "compacted": None,
        "cache_hit": None,
        "system_tokens": None,
        "summary_tokens_breakdown": None,
        "user_tokens": None,
        "assistant_tokens": None,
        "tool_tokens": None,
        "original_tokens": None,
        "retained_tokens": None,
        "omitted_tokens": None,
        "message_index": None,
    }

    @classmethod
    def create(cls, event_type: str, **data: Any) -> "Event":
        return cls(type=event_type, data={key: value for key, value in data.items() if value is not None})

    def __getattr__(self, name: str) -> Any:
        if name in self.data:
            return self.data[name]
        if name in self._default_values:
            return self._default_values[name]
        raise AttributeError(name)

    @staticmethod
    def text(content: str) -> "Event":
        return Event.create("text", content=content)

    @staticmethod
    def reasoning(content: str) -> "Event":
        return Event.create("reasoning", content=content)

    @staticmethod
    def tool_call(name: str, arguments: str) -> "Event":
        return Event.create("tool_call", name=name, arguments=arguments)

    @staticmethod
    def tool_result(name: str, result: str) -> "Event":
        return Event.create("tool_result", name=name, result=result)

    @staticmethod
    def done() -> "Event":
        return Event.create("done")

    @staticmethod
    def error(message: str) -> "Event":
        return Event.create("error", error_msg=message)

    @staticmethod
    def session_created(session_id: str) -> "Event":
        return Event.create("session_created", session_id=session_id)

    @staticmethod
    def context_compression(**kwargs) -> "Event":
        return Event.create("context_compression", **kwargs)

    @staticmethod
    def context_usage(**kwargs) -> "Event":
        return Event.create("context_usage", **kwargs)

    @staticmethod
    def context_pruning(**kwargs) -> "Event":
        return Event.create("context_pruning", **kwargs)

    def model_dump(self, **kwargs) -> dict:
        """自定义序列化，将 error_msg 映射为 error 键"""
        exclude_none = bool(kwargs.get("exclude_none", False))
        return self._flat_payload(exclude_none=exclude_none)

    @model_serializer(mode="plain")
    def serialize(self) -> dict[str, Any]:
        return self._flat_payload(exclude_none=False)

    def _flat_payload(self, exclude_none: bool = False) -> dict[str, Any]:
        payload = {"type": self.type, **self.data}
        if "error_msg" in payload:
            payload["error"] = payload.pop("error_msg")
        if exclude_none:
            payload = {key: value for key, value in payload.items() if value is not None}
        return payload
