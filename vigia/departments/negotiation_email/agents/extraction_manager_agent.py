from vigia.services import llm_service

class EmailManagerAgent:
    """Gerente (GoT): Consolida os relatórios dos especialistas de extração em um único JSON."""
    def __init__(self):
        self.system_prompt = """
        Você é o gerente de análise. Sua tarefa é consolidar múltiplos relatórios JSON de seus especialistas em um único relatório final coeso.
        Os relatórios são: dados do assunto, análise jurídico-financeira e estágio da negociação.
        Combine todas as informações em um único objeto JSON, eliminando redundâncias e garantindo uma estrutura clara e completa.
        Não invente dados. Se um campo não estiver presente nos relatórios de entrada, não o inclua.
        Retorne APENAS o objeto JSON consolidado.
        """
    async def execute(self, subject_data: str, legal_financial_data: str, stage_data: str) -> str:
        combined_input = f"""
        RELATÓRIO 1 (Dados do Assunto):
        {subject_data}

        RELATÓRIO 2 (Análise Jurídico-Financeira):
        {legal_financial_data}

        RELATÓRIO 3 (Estágio da Negociação):
        {stage_data}
        """
        return await llm_service.llm_call(self.system_prompt, combined_input)