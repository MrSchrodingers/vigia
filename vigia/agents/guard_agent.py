# vigia/agents/guard_agent.py
from ..services import llm_service

class PromptGuardAgent:
    def __init__(self):
        self.system_prompt = """
        Você é um Auditor de Conformidade de IA. Sua única tarefa é verificar se uma
        saída de IA ('OUTPUT') segue estritamente as regras de um prompt ('PROMPT ORIGINAL').
        Você é implacável e focado em regras, não no conteúdo.
        Responda APENAS com um objeto JSON.
        """

    async def execute(self, original_prompt: str, agent_output: str) -> str:
        # ToT/GoT Prompt: Decompõe a tarefa de verificação em passos lógicos.
        user_prompt = f"""
        Analise o PROMPT ORIGINAL e o OUTPUT abaixo.

        --- PROMPT ORIGINAL ---
        {original_prompt}
        ---

        --- OUTPUT ---
        {agent_output}
        ---

        Siga estes passos de raciocínio:
        1. Identifique as regras de formatação explícitas no PROMPT ORIGINAL (ex: 'Responda APENAS com JSON', 'Não inclua explicações', 'Use as chaves X e Y').
        2. Verifique se o OUTPUT viola ALGUMA dessas regras.
        3. Responda com um JSON contendo 'compliance_status' ('OK' ou 'FALHA') e 'detalhes'.
           Se for 'FALHA', o campo 'detalhes' deve conter uma lista das regras violadas.
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

guard_agent = PromptGuardAgent()