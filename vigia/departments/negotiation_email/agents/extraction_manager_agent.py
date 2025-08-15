from .base_llm_agent import BaseLLMAgent

class EmailManagerAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Una 3 relatórios JSON em 1:
        • Preserve todas as chaves únicas.
        • Se duas chaves colidem, prefira a não-nula; se ambas não-nulas, use a mais recente
          (considerando ordem Stage → Legal → Subject).
        • Ordem de saída: assunto ▸ proposta ▸ estágio ▸ argumentos ▸ status.
        Retorne apenas o JSON consolidado.
        """
        super().__init__(specific_prompt, expects_json=True)

    async def execute(self, *reports: str) -> str:
        joined = "\n\n---\n\n".join(reports)
        return await self._llm_call(joined)


class EmailDirectorAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Dada a análise consolidada (dados + temperatura) escolha **UMA** ação:
        Ferramentas = ["create_draft_reply","forward_to_department",
                       "Calendar","alert_supervisor"].
        • Se nenhuma ação prática necessária → devolva {"resumo_estrategico": str}.
        • Caso contrário → {"acao":{"nome_ferramenta": str,"parametros":{...}}}.
        """
        super().__init__(specific_prompt, expects_json=True)

    async def execute(self, extraction_report: str, temperature_report: str,
                      conversation_id: str) -> str:
        context = (
            f"ID_CONVERSA: {conversation_id}\n\n"
            f"=== RELATÓRIO DADOS ===\n{extraction_report}\n\n"
            f"=== RELATÓRIO TEMPERATURA ===\n{temperature_report}"
        )
        return await self._llm_call(context)
