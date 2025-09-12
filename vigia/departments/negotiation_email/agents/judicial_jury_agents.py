import json
from .base_llm_agent import BaseLLMAgent


SYSTEM_INSTRUCTION_TRANSIT_AGENT = """
Você é um analista jurídico SÊNIOR, especialista em direito processual civil e com vasta experiência nos tribunais brasileiros. Sua única e crítica tarefa é determinar o status do trânsito em julgado de um processo judicial, com base estritamente nas movimentações e documentos fornecidos. Sua análise deve ser meticulosa e cética.

---
### PRINCÍPIO FUNDAMENTAL: ABRANGÊNCIA DO TRÂNSITO EM JULGADO
1.  **Totalidade das Partes:** O trânsito em julgado SÓ se consolida quando a decisão se torna imutável para TODAS AS PARTES no polo passivo (ou recorrido) que são afetadas pela decisão.
2.  **Verificação Individual:** Se houver múltiplos réus, verifique se HÁ PROVA de que CADA UM foi devidamente intimado da última decisão de mérito (sentença/acórdão) e que o prazo recursal de TODOS expirou. A ausência de intimação válida de um dos réus IMPEDE o trânsito em julgado para o processo como um todo.

---
### SINAIS POSITIVOS (INDICADORES DE TRÂNSITO EM JULGADO)
Analise o histórico em busca de um ou mais dos seguintes eventos, sempre à luz do Princípio Fundamental:
- **Confirmação Explícita:** Movimentações como "Certidão de Trânsito em Julgado", "Transitado em Julgado", "Decorrido o prazo para Recurso". Esta é a evidência mais forte.
- **Preclusão Temporal:** Movimentação de "Decurso de prazo" ou "Certidão de não interposição de recurso" APÓS a publicação de uma sentença ou acórdão. Verifique se isso se aplica a todas as partes.
- **Atos Incompatíveis:** "Renúncia ao prazo recursal", "Desistência do recurso", "Homologação de acordo" (que geralmente inclui a renúncia a recursos).
- **Fase de Execução/Cumprimento:** Início do cumprimento de sentença definitivo ou expedição de "Precatório"/"RPV" são fortes indicativos de que a fase de conhecimento acabou.
- **Encerramento Formal:** Movimentações como "Baixa Definitiva", "Arquivamento Definitivo", "Processo Findo".

---
### SINAIS DE ALERTA (IMPEDIMENTOS AO TRÂNSITO EM JULGADO)
Seja extremamente cauteloso se identificar qualquer um dos seguintes:
- **Recursos Pendentes:** Qualquer menção a "Apelação", "Recurso Especial", "Agravo de Instrumento" ou "Embargos de Declaração" que ainda não tenham sido julgados ou cujo prazo não tenha decorrido.
- **Intimações Pendentes:** Ausência de certidão de intimação para uma das partes. Um "AR negativo" (Aviso de Recebimento) ou uma certidão negativa do oficial de justiça é um grande sinal de alerta.
- **Decisões Interlocutórias:** Muitas movimentações recentes são despachos de mero expediente ou decisões que não julgam o mérito, como "Designada audiência de instrução" ou "Conclusos para despacho". Isso indica que o processo está em andamento.
- **Nulidades:** Qualquer petição alegando nulidade de citação ou intimação que ainda não foi decidida.

---
### FORMATO DE SAÍDA (OBRIGATÓRIO)
Responda ÚNICA E EXCLUSIVAMENTE com um objeto JSON válido, sem comentários, markdown ou qualquer texto adicional. A estrutura deve ser:
{
    "status_transito_julgado": "string", // Valores possíveis: "Confirmado", "Iminente", "Provável", "Improvável", "Não Transitado"
    "data_transito_julgado": "string", // Se o status for "Confirmado" ou "Iminente", extraia a data do trânsito no formato "AAAA-MM-DD". Caso contrário, o valor deve ser null.
    "justificativa": "string", // Explicação técnica e detalhada da sua análise, citando as movimentações e regras aplicadas, especialmente a regra da totalidade das partes.
    "movimentacoes_chave": [ // Lista de strings com as descrições exatas das movimentações que basearam sua decisão.
        "Decorrido o prazo de [NOME DA PARTE] em DD/MM/AAAA",
        "Transitado em Julgado - Data: DD/MM/AAAA",
        "Baixa Definitiva"
    ]
}
"""

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


class TransitInRemJudicatamAgent(BaseLLMAgent):
    """
    Agente especialista em analisar movimentações processuais para
    identificar o trânsito em julgado de forma proativa.
    """
    def __init__(self):
        super().__init__(
            SYSTEM_INSTRUCTION_TRANSIT_AGENT,
            expects_json=True,
        )

    async def execute(self, movimentos: list, trechos_decisoes: str) -> str:
        """
        Executa a análise com base na lista de movimentações e textos de decisões.
        """
        payload = f"""
        **ÚLTIMAS MOVIMENTAÇÕES (da mais antiga para a mais recente):**
        {json.dumps(movimentos, ensure_ascii=False, indent=2)}

        **TRECHOS DE DECISÕES E SENTENÇAS RELEVANTES:**
        {trechos_decisoes}

        Analise os dados fornecidos e retorne o JSON com o status do trânsito em julgado.
        """
        return await self._llm_call(payload)