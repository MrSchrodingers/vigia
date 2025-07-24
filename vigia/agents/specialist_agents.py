from ..services import llm_service

class ExtractorAgent:
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt

    async def execute(self, conversation_history: str, current_date: str) -> str:
        user_prompt = f"""
        Considere que a data de hoje é {current_date}.
        Analise o histórico da conversa e o contexto do CRM abaixo.
        Sua tarefa é preencher o JSON com o máximo de detalhes possível.
        
        **INSTRUÇÃO CRÍTICA SOBRE DATAS:** Resolva QUALQUER data relativa (como 'dia 20', 'semana que vem', 'amanhã', 'próxima segunda') para o formato AAAA-MM-DD. Preencha 'data_final_acordada_absoluta' se for uma data de pagamento, ou 'data_follow_up_agendada' se for uma data de retorno ou continuação da conversa.

        Histórico e Contexto:
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
    {{"resumo_negociacao": "...", "status": "...", "valores": {{}}, "prazos": {{"data_proposta_cliente": null, "data_final_acordada_absoluta": null, "data_follow_up_agendada": null}}, "objeto_negociacao": "...", "pontos_chave_cliente": []}}
    """
)

inquisitive_agent = ExtractorAgent(
    system_prompt="""
    Você é um assistente de extração de dados sênior, especialista em interpretar o contexto de negociações.
    Preencha o schema JSON abaixo de forma completa, fazendo inferências lógicas.
    Sempre que encontrar uma proposta, estruture-a como um objeto {"descricao": "...", "valor_total": ...}.
    Se o cliente diz 'Sim' para uma proposta, determine o status como 'Acordo Fechado'.
    Sintetize os argumentos do cliente em 'pontos_chave_cliente'.
    Responda APENAS com o objeto JSON, sem nenhum texto adicional.
    Schema:
    {{"resumo_negociacao": "...", "status": "...", "valores": {{}}, "prazos": {{"data_proposta_cliente": null, "data_final_acordada_absoluta": null, "data_follow_up_agendada": null}}, "objeto_negociacao": "...", "pontos_chave_cliente": []}}
    """
)