from ..services import llm_service

class BusinessDirectorAgent:
    def __init__(self):
        self.system_prompt = """
        Você é o Diretor Comercial. Sua função é tomar uma decisão estratégica
        baseada nos relatórios consolidados de seus departamentos.
        Seu foco é: a negociação está progredindo bem? Precisamos intervir?
        Responda APENAS com um objeto JSON, seguindo estritamente o schema fornecido.
        """

    async def execute(self, executive_summary: str) -> str:
        user_prompt = f"""
        Abaixo está o resumo executivo de uma negociação em andamento.
        Com base em TUDO, avalie o status geral e decida a próxima ação estratégica.

        --- RESUMO EXECUTIVO ---
        {executive_summary}
        ---

        Sua decisão estratégica (JSON com 'status_geral', 'proxima_acao_sugerida' e 'detalhes_acao'):
        - O campo 'detalhes_acao' deve conter uma breve justificativa ou os próximos passos específicos. Se não houver detalhes, deixe como null.
        - Exemplos de proxima_acao_sugerida: 'Monitorar Pagamento', 'Alertar Supervisor Humano', 'Encaminhar ao Jurídico'.
        
        Schema de resposta: {{"status_geral": "...", "proxima_acao_sugerida": "...", "detalhes_acao": "..."}}
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

director_agent = BusinessDirectorAgent()