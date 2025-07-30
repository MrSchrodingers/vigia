import json
from typing import Union

from .base_llm_agent import BaseLLMAgent


class JudicialNegotiationAdvisorAgent(BaseLLMAgent):
    """Analista especializado em orientar o negociador sobre o próximo passo judicial.

    A lógica TOT + GOT fica delegada ao modelo via *specific_prompt* – o grafo é
    descrito na própria instrução. Aqui, apenas garantimos que **execute** envie
    o payload em JSON bruto (string) para a chamada do LLM.
    """

    def __init__(self) -> None:
        specific_prompt = """
        CONTEXTO:
        • Você é um advogado sênior de contencioso bancário.
        • Recebe JSON {extract, temperature, kpis, crm_context}.

        PEÇA:
        1. Gere até 3 opções de próxima ação (estratégia + justificativa legal).
        2. Para cada opção, estime: prob_sucesso, prazo_dias, custo_R$.
        3. Escolha a MELHOR e retorne:
           {
             "acao_recomendada": {...},
             "alternativas": [{...},{...}],
             "racional_juridico": str,
             "confidence": 0-1
           }

        RESTRAINTS:
        - Cite artigos / súmulas aplicáveis.
        - Use moeda “R$” e datas ISO-8601.
        - Sem linguagem emocional.
        """
        super().__init__(specific_prompt)

    # ---------------------------------------------------------------------
    # Public API required by BaseLLMAgent (abstract method)
    # ---------------------------------------------------------------------

    async def execute(self, payload: Union[str, dict]) -> str:  # type: ignore[override]
        """Recebe o contexto completo e devolve a recomendação.

        Aceita tanto *dict* quanto string JSON.  Sempre serializa para string
        antes de repassar ao LLM.
        """
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False)
        return await self._llm_call(payload)
