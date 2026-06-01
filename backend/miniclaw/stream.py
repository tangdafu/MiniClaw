from .react_context import ModelTurn
from .types import Event


class ToolCallParser:
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
                "function": {"name": "", "arguments": ""},
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


class StreamAccumulator:
    def __init__(self):
        self.assistant_message: dict = {"role": "assistant", "content": "", "reasoning_content": ""}
        self.parser = ToolCallParser()

    def feed_delta(self, delta) -> list[Event]:
        events: list[Event] = []

        if getattr(delta, "reasoning_content", None):
            self.assistant_message["reasoning_content"] += delta.reasoning_content
            events.append(Event.reasoning(delta.reasoning_content))

        if delta.content:
            self.assistant_message["content"] += delta.content
            events.append(Event.text(delta.content))

        if delta.tool_calls:
            for tool_call in delta.tool_calls:
                self.parser.feed(tool_call)

        return events

    def to_turn(self) -> ModelTurn:
        tool_calls = self.parser.get_tool_calls()
        assistant_message = dict(self.assistant_message)
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        return ModelTurn(
            assistant_message=assistant_message,
            tool_calls=tool_calls,
            text=assistant_message.get("content", ""),
            reasoning_content=assistant_message.get("reasoning_content", ""),
        )
