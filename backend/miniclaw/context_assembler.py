class ContextAssembler:
    def __init__(self, system_prompt: str | None = None, window_size: int = 20):
        self.system_prompt = system_prompt
        self.window_size = window_size if window_size > 0 else 20

    def build(self, messages: list[dict]) -> list[dict]:
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})

        for message in self._select_window(messages):
            result.append(self._clean_message(message))

        return result

    def _select_window(self, messages: list[dict]) -> list[dict]:
        if len(messages) <= self.window_size:
            return list(messages)

        start = len(messages) - self.window_size
        selected = list(messages[start:])
        selected = self._repair_leading_tool_messages(messages, start, selected)
        return self._drop_orphan_leading_tool_messages(selected)

    def _repair_leading_tool_messages(
        self,
        messages: list[dict],
        start: int,
        selected: list[dict],
    ) -> list[dict]:
        if not selected or selected[0].get("role") != "tool":
            return selected

        leading_tool_ids = []
        for message in selected:
            if message.get("role") != "tool":
                break
            tool_call_id = message.get("tool_call_id")
            if tool_call_id:
                leading_tool_ids.append(tool_call_id)

        assistant = self._find_matching_assistant(messages[:start], leading_tool_ids)
        if not assistant:
            return selected

        return [assistant, *selected]

    def _find_matching_assistant(self, messages: list[dict], tool_call_ids: list[str]) -> dict | None:
        tool_call_id_set = set(tool_call_ids)
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            message_tool_ids = {
                tool_call.get("id")
                for tool_call in message.get("tool_calls", [])
                if tool_call.get("id")
            }
            if tool_call_id_set and tool_call_id_set.issubset(message_tool_ids):
                return message
        return None

    def _drop_orphan_leading_tool_messages(self, messages: list[dict]) -> list[dict]:
        first_non_tool = 0
        while first_non_tool < len(messages) and messages[first_non_tool].get("role") == "tool":
            first_non_tool += 1
        return messages[first_non_tool:]

    def _clean_message(self, message: dict) -> dict:
        clean_message = dict(message)
        if clean_message.get("reasoning_content") == "":
            clean_message.pop("reasoning_content", None)
        return clean_message
