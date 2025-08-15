from .base_llm_agent import BaseLLMAgent

# JSON Schema minimalista compatível com Gemini (sem 'additionalProperties', 'pattern', etc.)
ARBITER_SCHEMA = {
    "type": "object",
    "required": ["acao_recomendada", "racional_juridico", "teses_consideradas", "confidence_score", "referencias"],
    "properties": {
        "acao_recomendada": {
            "type": "object",
            "required": ["estrategia", "proxima_acao"],
            "properties": {
                "estrategia": {"type": "string"},
                "proxima_acao": {"type": "string"}
            }
        },
        "racional_juridico": {"type": "string"},
        "teses_consideradas": {
            "type": "object",
            "required": ["conservadora", "estrategica"],
            "properties": {
                "conservadora": {"type": "string"},
                "estrategica": {"type": "string"}
            }
        },
        "confidence_score": {"type": "number"},
        "referencias": {
            "type": "array",
            "items": {"type": "string"}
        }
    }
}


class ConservativeAdvocateAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        VOCÊ É UM ADVOGADO SÊNIOR ESPECIALISTA EM CONTENCIOSO CÍVEL, COM PERFIL CONSERVADOR E METÓDICO.
        OBJETIVO: propor a estratégia MAIS SEGURA e com menor risco jurídico.
        SAÍDA: JSON puro com: { "tese": string, "justificativa_legal": string, "proxima_acao_sugerida": string }
        """
        super().__init__(specific_prompt, expects_json=True)

    async def execute(self, context: str) -> str:
        return await self._llm_call(context)


class StrategicAdvocateAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        VOCÊ É UM NEGOCIADOR ESTRATEGISTA ORIENTADO A RESULTADOS.
        OBJETIVO: melhor resultado financeiro no menor tempo.
        SAÍDA: JSON puro com: { "tese": string, "justificativa_estrategica": string, "proxima_acao_sugerida": string }
        """
        super().__init__(specific_prompt, expects_json=True)

    async def execute(self, context: str) -> str:
        return await self._llm_call(context)


class JudicialArbiterAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        VOCÊ É O ÁRBITRO FINAL (JUIZ).
        TAREFA: analisar tese conservadora e estratégica e decidir.

        REGRAS:
        - Responda **apenas** JSON válido.
        - Se mencionar fato ancorado em documento/ato, cite 〔doc_id〕 no texto e liste o doc_id em "referencias".
        - Campos obrigatórios: 
          acao_recomendada.estrategia, acao_recomendada.proxima_acao, 
          racional_juridico, teses_consideradas.conservadora, teses_consideradas.estrategica, 
          confidence_score (0..1), referencias (array de strings).
        """
        super().__init__(specific_prompt, expects_json=True, json_schema=ARBITER_SCHEMA)

    async def execute(self, context: str, tese_conservadora: str, tese_estrategica: str) -> str:
        payload = f"""
        CONTEXTO:
        {context}

        TESE_CONSERVADORA:
        {tese_conservadora}

        TESE_ESTRATEGICA:
        {tese_estrategica}

        Gere o JSON final conforme o schema.
        """
        return await self._llm_call(payload)
