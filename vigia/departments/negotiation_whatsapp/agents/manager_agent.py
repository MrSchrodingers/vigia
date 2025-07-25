from vigia.services import llm_service

class ValidationManagerAgent:
    def __init__(self):
        self.system_prompt = """
        Você é um gerente de análise de negociações sênior, um mestre em lógica,
        síntese e atenção aos detalhes. Sua função é atuar como o passo final de validação
        em uma cadeia de pensamento (Tree of Thoughts), consolidando múltiplas análises
        em um único relatório final que representa a verdade absoluta dos fatos.
        Responda APENAS com o objeto JSON final.
        """

    async def execute(self, extraction_results: list[str], conversation_history: str, current_date: str) -> str:
        user_prompt = f"""
        A data de hoje é {current_date}.

        **TAREFA CRÍTICA:** Você recebeu duas análises preliminares de seus analistas.
        Sua missão é usar estas análises como "pensamentos", compará-las com a
        "Fonte da Verdade" (o histórico completo), resolver discrepâncias e produzir um
        único relatório JSON final e consolidado.

        **FONTE DA VERDADE (Histórico da Conversa e Contexto do CRM):**
        ---
        {conversation_history}
        ---

        **PENSAMENTO 1 (Análise do Especialista Cauteloso):**
        ---
        {extraction_results[0]}
        ---

        **PENSAMENTO 2 (Análise do Especialista Inquisitivo):**
        ---
        {extraction_results[1]}
        ---

        **PROCESSO DE SÍNTESE E VALIDAÇÃO (SIGA ESTRITAMENTE):**
        1.  **Comparar e Verificar:** Compare os dois relatórios com a "Fonte da Verdade". Resolva todas as divergências.
        2.  **INSTRUÇÃO CRÍTICA SOBRE DATAS:** Preste muita atenção ao campo `prazos`. Resolva TODAS as datas relativas (como 'semana que vem', 'próxima segunda', 'amanhã') para o formato AAAA-MM-DD. Se a data for para um pagamento, preencha `data_final_acordada_absoluta`. Se for para um retorno do cliente, preencha `data_follow_up_agendada`.
        3.  **Sintetizar:** Crie o relatório final, combinando as informações corretas e preenchendo quaisquer lacunas com base na sua leitura superior da "Fonte da Verdade".
        4.  **Formato:** Sua resposta final deve ser um único e bem formatado objeto JSON, seguindo o schema abaixo.

        **Schema JSON de Saída:**
        {{"resumo_negociacao": "...", "status": "...", "valores": {{}}, "prazos": {{"data_proposta_cliente": null, "data_final_acordada_absoluta": null, "data_follow_up_agendada": null}}, "objeto_negociacao": "...", "pontos_chave_cliente": []}}
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

manager_agent = ValidationManagerAgent()