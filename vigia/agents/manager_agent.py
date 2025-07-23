from ..services import llm_service

class ValidationManagerAgent:
    def __init__(self):
        self.system_prompt = """
        Você é um gerente de análise de negociações, mestre em interpretar conversas complexas
        e consolidar informações para criar um relatório executivo preciso.
        Sua tarefa é analisar o histórico completo e as análises preliminares de seus analistas
        para produzir a versão final e definitiva da verdade.
        Responda APENAS com o objeto JSON final.
        """

    # O gestor também precisa da data e do histórico
    async def execute(self, extraction_results: list[str], conversation_history: str, current_date: str) -> str:
        # ToT/GoT Prompt: Pede para o LLM usar as análises dos especialistas como "pontos de vista"
        # para formar uma conclusão superior, usando o texto original como fonte da verdade.
        user_prompt = f"""
        Considere que a data de hoje é {current_date}.

        TAREFA: Crie um relatório JSON final e consolidado sobre a negociação abaixo.

        FONTE DA VERDADE (HISTÓRICO COMPLETO):
        ---
        {conversation_history}
        ---

        ANÁLISES PRELIMINARES DOS SEUS ANALISTAS (use como guia, mas confie na fonte da verdade):
        ---
        {extraction_results}
        ---

        INSTRUÇÕES DETALHADAS:
        1.  **Status:** Baseado na última mensagem, determine o 'status'. Se o cliente disse 'Sim' para a última proposta do negociador, o status é 'Acordo Fechado'. Caso contrário, é 'Em Andamento' ou 'Pendente'.
        2.  **Valores e Prazos:** Preencha todos os campos de valores e prazos. Para a 'data_final_acordada_absoluta', resolva datas como 'dia 20' para o formato AAAA-MM-DD.
        3.  **Resumo e Pontos-Chave:** Crie um resumo conciso e liste os principais argumentos/dificuldades do cliente.
        4.  **Formato:** Sua resposta final deve ser um único e bem formatado objeto JSON, seguindo o schema abaixo.

        Schema JSON de Saída:
        {{"resumo_negociacao": "...", "status": "...", "valores": {{"valor_original_mencionado": 0.0, "propostas_negociador": [], "contrapropostas_cliente": [], "valor_final_acordado": null}}, "prazos": {{"data_proposta_cliente": null, "data_final_acordada_absoluta": null}}, "objeto_negociacao": "...", "pontos_chave_cliente": []}}
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

manager_agent = ValidationManagerAgent()