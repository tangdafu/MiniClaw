class ContextAssembler:
    def __init__(self, system_prompt: str | None = None):
        self.system_prompt = system_prompt

    def build(self, messages: list[dict]) -> list[dict]:
        result = []
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
        result.extend(self._clean_message(message) for message in messages)
        return result

    def _clean_message(self, message: dict) -> dict:
        clean_message = dict(message)
        if clean_message.get("reasoning_content") == "":
            clean_message.pop("reasoning_content", None)
        return clean_message
