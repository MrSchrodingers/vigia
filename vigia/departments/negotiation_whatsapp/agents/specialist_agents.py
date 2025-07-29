from vigia.services import llm_service

class ExtractorAgent:
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt

    async def execute(self, conversation_history: str, current_date: str) -> str:
        user_prompt = f"""
        Considere que a data de hoje é {current_date}.
        Analise o histórico da conversa e o contexto do CRM abaixo.
        Sua tarefa é preencher o JSON com o máximo de detalhes possível, seguindo o schema.
        
        **INSTRUÇÃO CRÍTICA SOBRE DATAS:** Resolva QUALQUER data relativa (como 'dia 20', 'semana que vem', 'amanhã', 'próxima segunda') para o formato AAAA-MM-DD. Preencha 'data_final_acordada_absoluta' se for uma data de pagamento, ou 'data_follow_up_agendada' se for uma data de retorno ou continuação da conversa.

        Histórico e Contexto:
        ---
        {conversation_history}
        ---
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

# Schema JSON mais flexível e descritivo
JSON_SCHEMA = """
{{
    "resumo_negociacao": "Um resumo conciso de toda a negociação até o momento.",
    "status": "O status atual da negociação (ex: 'Contato Inicial', 'Em Negociação', 'Aguardando Retorno do Cliente', 'Acordo Fechado').",
    "valores": {{
        "descricao": "Opcional. Uma descrição do valor principal em negociação.",
        "valor_total": "Opcional. O valor numérico principal da dívida ou proposta."
    }},
    "prazos": {{
        "data_proposta_cliente": "Opcional. A data em que o cliente propôs algo, em formato AAAA-MM-DD.",
        "data_final_acordada_absoluta": "Opcional. A data final acordada para um pagamento, em formato AAAA-MM-DD.",
        "data_follow_up_agendada": "Opcional. A data agendada para um próximo contato, em formato AAAA-MM-DD."
    }},
    "objeto_negociacao": "O que está sendo negociado (ex: 'Ressarcimento de danos', 'Quitação de débito').",
    "pontos_chave_cliente": [
        "Uma lista de argumentos, dúvidas ou pontos importantes levantados pelo CLIENTE."
    ]
}}
"""

cautious_agent = ExtractorAgent(
    system_prompt=f"""
    Você é um assistente de extração de dados extremamente literal e cauteloso.
    Preencha o schema JSON abaixo APENAS com informações que estão EXPLICITAMENTE escritas no texto.
    Se uma informação não for explícita, deixe o campo como null ou o objeto/lista vazios.
    Responda APENAS com o objeto JSON, sem nenhum texto adicional.
    Schema:
    {JSON_SCHEMA}
    """
)

inquisitive_agent = ExtractorAgent(
    system_prompt=f"""
    Você é um assistente de extração de dados sênior, especialista em interpretar o contexto de negociações.
    Preencha o schema JSON abaixo de forma completa, fazendo inferências lógicas.
    Sempre que encontrar uma proposta, tente preencher o objeto 'valores'.
    Se o cliente diz 'Sim' para uma proposta, determine o status como 'Acordo Fechado'.
    Sintetize os argumentos do cliente em 'pontos_chave_cliente'.
    Responda APENAS com o objeto JSON, sem nenhum texto adicional.
    Schema:
    {JSON_SCHEMA}
    """
)