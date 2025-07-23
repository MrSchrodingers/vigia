from ..services import llm_service

class ExtractorAgent:
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt

    # Método execute agora aceita a data atual
    async def execute(self, conversation_history: str, current_date: str) -> str:
        user_prompt = f"""
        Considere que a data de hoje é {current_date}.
        Analise o histórico da conversa de negociação abaixo.
        Sua tarefa é preencher o JSON com o máximo de detalhes possível.
        Resolva todas as datas relativas (como 'dia 20', 'em agosto') para o formato AAAA-MM-DD.

        Histórico da Conversa:
        ---
        {conversation_history}
        ---
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

# FUNCIONÁRIO 1: O Cauteloso (Foco em fatos explícitos)
cautious_agent = ExtractorAgent(
    system_prompt="""
    Você é um assistente de extração de dados extremamente literal e cauteloso.
    Preencha o schema JSON abaixo APENAS com informações que estão EXPLICITAMENTE escritas no texto.
    Se uma informação não for explícita (ex: o cliente diz 'Sim' para uma proposta), não preencha o campo 'valor_final_acordado'. Deixe o campo como null.
    Não faça inferências. Apenas reporte os fatos diretos.
    Responda APENAS com o objeto JSON.
    Schema:
    {{"resumo_negociacao": "...", "status": "...", "valores": {{"valor_original_mencionado": 0.0, "propostas_negociador": [], "contrapropostas_cliente": [], "valor_final_acordado": null}}, "prazos": {{"data_proposta_cliente": null, "data_final_acordada_absoluta": null}}, "objeto_negociacao": "...", "pontos_chave_cliente": []}}
    """
)

# FUNCIONÁRIO 2: O Inferencial (Foco no quadro geral)
inquisitive_agent = ExtractorAgent(
    system_prompt="""
    Você é um assistente de extração de dados sênior, especialista em interpretar o contexto de negociações.
    Preencha o schema JSON abaixo de forma completa, fazendo inferências lógicas.
    Se o cliente diz 'Sim' para a proposta final do negociador de pagar no 'dia 20', determine o status como 'Acordo Fechado' e preencha a 'data_final_acordada_absoluta' com a data resolvida.
    Sintetize os argumentos do cliente em 'pontos_chave_cliente'.
    Responda APENAS com o objeto JSON.
    Schema:
    {{"resumo_negociacao": "...", "status": "...", "valores": {{"valor_original_mencionado": 0.0, "propostas_negociador": [], "contrapropostas_cliente": [], "valor_final_acordado": null}}, "prazos": {{"data_proposta_cliente": null, "data_final_acordada_absoluta": null}}, "objeto_negociacao": "...", "pontos_chave_cliente": []}}
    """
)