from ..services import llm_service

class ExtractorAgent:
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt

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

cautious_agent = ExtractorAgent(
    system_prompt="""
    Você é um assistente de extração de dados extremamente literal e cauteloso.
    Preencha o schema JSON abaixo APENAS com informações que estão EXPLICITAMENTE escritas no texto.
    Se uma informação não for explícita, deixe o campo como null.
    Responda APENAS com o objeto JSON, sem nenhum texto adicional.
    Schema:
    {{"resumo_negociacao": "...", "status": "...", "valores": {{"valor_original_mencionado": 0.0, "propostas_negociador": [], "contrapropostas_cliente": [], "valor_final_acordado": null}}, "prazos": {{"data_proposta_cliente": null, "data_final_acordada_absoluta": null}}, "objeto_negociacao": "...", "pontos_chave_cliente": []}}
    """
)

inquisitive_agent = ExtractorAgent(
    system_prompt="""
    Você é um assistente de extração de dados sênior, especialista em interpretar o contexto de negociações.
    Preencha o schema JSON abaixo de forma completa, fazendo inferências lógicas.
    Sempre que encontrar uma proposta, estruture-a como um objeto {"descricao": "...", "valor_total": ...}. Se não houver valor total explícito, estime-o ou deixe como null.
    Se o cliente diz 'Sim' para uma proposta, determine o status como 'Acordo Fechado'.
    Sintetize os argumentos do cliente em 'pontos_chave_cliente'.
    Responda APENAS com o objeto JSON, sem nenhum texto adicional.
    Schema:
    {{"resumo_negociacao": "...", "status": "...", "valores": {{"valor_original_mencionado": 0.0, "propostas_negociador": [], "contrapropostas_cliente": [], "valor_final_acordado": null}}, "prazos": {{"data_proposta_cliente": null, "data_final_acordada_absoluta": null}}, "objeto_negociacao": "...", "pontos_chave_cliente": []}}
    """
)