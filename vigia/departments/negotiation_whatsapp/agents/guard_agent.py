from vigia.services import llm_service

class PromptGuardAgent:
    def __init__(self):
        self.system_prompt = """
        Você é um autômato lógico, um Auditor de Conformidade de IA. Sua única tarefa é verificar se uma
        saída de IA ('OUTPUT') segue estritamente as regras de formatação de um prompt ('PROMPT ORIGINAL').
        Você é implacável, focado em regras e ignora completamente o significado ou a qualidade do conteúdo.

        NÃO É seu trabalho:
        - Avaliar se o conteúdo do OUTPUT está correto.
        - Resumir o OUTPUT.
        - Corrigir o OUTPUT.

        Seu trabalho é APENAS verificar a conformidade com as regras de formatação.
        Responda APENAS com um único e bem-formado objeto JSON.
        """

    async def execute(self, original_prompt: str, agent_output: str) -> str:
        # O user_prompt agora inclui um exemplo claro de falha para guiar o raciocínio.
        user_prompt = f"""
        Analise o PROMPT ORIGINAL e o OUTPUT abaixo.

        --- PROMPT ORIGINAL ---
        {original_prompt}
        ---

        --- OUTPUT ---
        {agent_output}
        ---

        Siga estes passos de raciocínio:
        1.  Identifique as regras de formatação explícitas no PROMPT ORIGINAL. As regras podem ser:
            - 'Responda APENAS com JSON'.
            - 'Não inclua explicações ou texto conversacional'.
            - 'O JSON deve ter as chaves X, Y e Z'.
            - 'O valor da chave X deve ser um dos seguintes: A, B, C'.
        2.  Compare o OUTPUT com CADA regra identificada.
        3.  Responda com um JSON contendo 'compliance_status' ('OK' ou 'FALHA') e 'detalhes'.
            - Se 'FALHA', o campo 'detalhes' DEVE conter uma lista de strings, onde cada string explica UMA regra violada e o motivo.

        EXEMPLO DE RACIOCÍNIO:
        - PROMPT ORIGINAL Exemplo: "Você é um classificador. Responda APENAS com um JSON contendo a chave 'status'."
        - OUTPUT Exemplo: "Claro! Aqui está a classificação: {{'status': 'Positivo'}}"
        - RACIOCÍNIO: O prompt tem a regra "Responda APENAS com um JSON". O output incluiu o texto "Claro! Aqui está a classificação: " antes do JSON. Isso viola a regra.
        - RESPOSTA JSON DO EXEMPLO:
          {{
            "compliance_status": "FALHA",
            "detalhes": [
              "Regra violada: 'Responda APENAS com um JSON'. Motivo: O output incluiu texto conversacional antes do objeto JSON."
            ]
          }}
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

guard_agent = PromptGuardAgent()