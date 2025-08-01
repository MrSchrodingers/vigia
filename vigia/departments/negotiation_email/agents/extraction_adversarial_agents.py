from .base_llm_agent import BaseLLMAgent

class ExtractionValidatorAgent(BaseLLMAgent):
    """
    Este agente atua como o "Discriminador" ou "Validador" em nossa arquitetura adversarial.
    Sua função é receber uma extração e criticá-la de forma rigorosa.
    """
    def __init__(self):
        specific_prompt = """
        Você é um Perito Auditor de Extração, extremamente cético e detalhista. Sua função é validar a precisão de um JSON extraído a partir de um texto.

        Você receberá o texto original e a extração JSON. Sua tarefa é encontrar qualquer erro, omissão ou má interpretação.

        **Seu Checklist de Validação:**
        1.  **Precisão dos Dados:** Os valores, prazos e condições no JSON correspondem EXATAMENTE ao que está no texto?
        2.  **Atribuição de Argumentos:** Os argumentos em "argumentos_nossos" e "argumentos_cliente" foram atribuídos corretamente com base no remetente ("De:")? Houve alguma inversão?
        3.  **Omissões:** Algum argumento ou condição importante foi deixado de fora da extração?
        4.  **Lógica do Status:** O "status_acordo" é uma conclusão lógica com base na última mensagem da conversa?

        **Formato da Resposta:**
        Retorne um JSON com sua análise.
        - Se a extração estiver perfeita, retorne: `{"is_valid": true, "critique": "A extração está precisa e completa."}`
        - Se encontrar erros, retorne: `{"is_valid": false, "critique": "Descreva o erro específico aqui.", "suggested_correction": "Sugira a correção necessária aqui."}`

        **Exemplo de Crítica:**
        `{"is_valid": false, "critique": "Erro de atribuição. A proposta de R$ 4.200,00 foi feita por 'nosso lado', mas foi listada em 'argumentos_cliente'.", "suggested_correction": "Mover a proposta de R$ 4.200,00 de 'argumentos_cliente' para 'argumentos_nossos'."}`
        """
        super().__init__(specific_prompt)

    async def execute(self, email_body: str, json_extraction: str) -> str:
        context = f"""
        TEXTO ORIGINAL PARA ANÁLISE:
        ---
        {email_body}
        ---

        EXTRAÇÃO JSON PARA VALIDAR:
        ---
        {json_extraction}
        ---

        Por favor, realize sua auditoria com base no checklist e retorne sua análise no formato JSON especificado.
        """
        return await self._llm_call(context)


class ExtractionRefinerAgent(BaseLLMAgent):
    """
    Este agente atua como o "Juiz" ou "Refinador".
    Ele recebe a extração inicial e a crítica do validador para produzir a versão final e definitiva.
    """
    def __init__(self):
        specific_prompt = """
        Você é o Juiz de Fatos, a autoridade final na interpretação de uma negociação.
        Sua tarefa é produzir a versão final e correta de uma extração de dados, considerando a tentativa inicial e a crítica de um auditor.

        Você receberá três informações:
        1.  O texto original completo.
        2.  A extração JSON inicial.
        3.  O relatório de validação do auditor (crítica).

        **Seu Processo de Decisão:**
        - Analise a crítica do auditor.
        - Se a crítica for válida, aplique as correções sugeridas à extração inicial para criar uma nova versão.
        - Se a crítica for inválida ou a extração inicial já estiver correta, ignore a crítica e mantenha a extração inicial como final.

        **IMPORTANTE:** Sua saída deve ser **SEMPRE** o objeto JSON final e completo, seguindo a estrutura de dados original, e nada mais. Não inclua explicações, apenas o JSON.
        """
        super().__init__(specific_prompt)

    async def execute(self, email_body: str, initial_extraction: str, validation_report: str) -> str:
        context = f"""
        TEXTO ORIGINAL COMPLETO:
        ---
        {email_body}
        ---

        EXTRAÇÃO JSON INICIAL (GERADOR):
        ---
        {initial_extraction}
        ---

        RELATÓRIO DE VALIDAÇÃO (AUDITOR):
        ---
        {validation_report}
        ---

        Com base em todas as informações, produza o JSON final e corrigido.
        """
        return await self._llm_call(context)