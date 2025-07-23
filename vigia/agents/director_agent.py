# vigia/agents/director_agent.py
from ..services import llm_service

class BusinessDirectorAgent:
    def __init__(self):
        self.system_prompt = """
        Você é o Diretor Comercial. Sua função é tomar uma decisão estratégica
        baseada nos relatórios consolidados de seus departamentos.
        Seu foco é: a negociação está progredindo bem? Precisamos intervir?
        Responda APENAS com um objeto JSON.
        """

    async def execute(self, executive_summary: str) -> str:
        # O prompt agora é mais rico, recebendo o resumo completo
        user_prompt = f"""
        Abaixo está o resumo executivo de uma negociação em andamento.
        Com base em TUDO, avalie o status geral e decida a próxima ação estratégica.

        --- RESUMO EXECUTIVO ---
        {executive_summary}
        ---

        Sua decisão estratégica (JSON com 'status_geral' e 'proxima_acao_sugerida'):
        Exemplos de proxima_acao_sugerida: 'Monitorar', 'Alertar supervisor humano', 'Enviar para retenção'.
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

director_agent = BusinessDirectorAgent()