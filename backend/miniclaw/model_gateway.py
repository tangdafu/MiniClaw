from typing import Any, Protocol

from openai import AsyncOpenAI


class ChatModelGateway(Protocol):
    async def create_chat_completion(self, **kwargs: Any) -> Any: ...


class OpenAIChatModelGateway:
    def __init__(self, client: AsyncOpenAI):
        self.client = client

    async def create_chat_completion(self, **kwargs: Any) -> Any:
        return await self.client.chat.completions.create(**kwargs)
