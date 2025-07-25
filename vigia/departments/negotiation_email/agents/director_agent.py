from vigia.services import llm_service

class EmailDirectorAgent:
    """
    O Diretor. Analisa os relatórios consolidados e decide a próxima ação, utilizando ferramentas.
    """
    def __init__(self):
        self.system_prompt = """
        Você é o Diretor de Negociações Estratégicas. Com base nos relatórios de Extração e Temperatura, decida a ÚNICA melhor ação.

        Ferramentas disponíveis:
        - `create_draft_reply(assunto: str, corpo_email: str, destinatario: str)`: Cria um rascunho de resposta.
        - `forward_to_department(departamento: str, nota: str)`: Encaminha a thread para um time interno (ex: "juridico").
        - `Calendar(assunto: str, data_inicio: str, participantes: list, nota: str)`: Agenda um lembrete ou reunião.
        - `alert_supervisor(motivo: str, urgencia: str)`: Alerta um supervisor sobre um ponto crítico.

        Se nenhuma ação for necessária, forneça um `resumo_estrategico` com o resultado e insights.
        Sua resposta DEVE ser um único objeto JSON, contendo a chave `acao` (com `nome_ferramenta` e `parametros`) ou a chave `resumo_estrategico`.
        """

    async def execute(self, extraction_report: str, temperature_report: str, conversation_id: str) -> str:
        full_context = f"""
        ID da Conversa para referência: {conversation_id}

        RELATÓRIO DE EXTRAÇÃO DE DADOS:
        {extraction_report}

        RELATÓRIO DE TEMPERATURA E COMPORTAMENTO:
        {temperature_report}
        """
        return await llm_service.llm_call(self.system_prompt, full_context)