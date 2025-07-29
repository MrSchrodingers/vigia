from abc import ABC, abstractmethod
from vigia.services import llm_service

class BaseLLMAgent(ABC):
    """
    Agente base que padroniza:
    • cabeçalho GoT/ToT
    • assinatura de execução
    • injeção de few-shot examples (quando existir)
    """
    ### ① HEADERS COMUNS (GoT + ToT) ###
    _intro_got_tot = (
        "💡 **Graph-of-Thought**: antes de responder, gere ideias em paralelo e "
        "eleja as 2 melhores.\n"
        "🌲 **Tree-of-Thought**: refine cada ideia por 2 níveis até chegar à "
        "conclusão. Responda **apenas** o resultado consolidado, nunca as notas."
    )

    def __init__(self, specific_system_prompt: str, few_shot: str | None = None):
        self.system_prompt = f"{self._intro_got_tot}\n\n{specific_system_prompt}".strip()
        self.few_shot = few_shot or ""

    async def _llm_call(self, user_input: str) -> str:
        prompt = f"{self.few_shot}\n\n{user_input}".strip()
        return await llm_service.llm_call(self.system_prompt, prompt)

    @abstractmethod
    async def execute(self, *args, **kwargs): ...
