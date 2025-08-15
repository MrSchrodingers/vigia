from abc import ABC, abstractmethod
from vigia.services import llm_service

class BaseLLMAgent(ABC):

    def __init__(self, specific_system_prompt: str, few_shot: str | None = None,
                 expects_json: bool = False, json_schema: dict | None = None):
        self.system_prompt = specific_system_prompt.strip()
        self.few_shot = (few_shot or "").strip()
        self.expects_json = expects_json
        self.json_schema = json_schema

    async def _llm_call(self, user_input: str, use_tools: bool = False) -> str:
        prompt = f"{self.few_shot}\n\n{user_input}".strip()
        return await llm_service.llm_call(
            system_prompt=self.system_prompt,
            user_prompt=prompt,
            use_tools=use_tools,
            expects_json=self.expects_json,
            json_schema=self.json_schema
        )

    @abstractmethod
    async def execute(self, *args, **kwargs):
        ...
