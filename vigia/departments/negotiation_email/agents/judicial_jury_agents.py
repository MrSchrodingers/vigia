import json
from .base_llm_agent import BaseLLMAgent

SYSTEM_INSTRUCTION_POST_SENTENCE_AGENT = """
Você é um analista jurídico SÊNIOR, especialista em direito processual civil, focado na fase recursal. Sua tarefa é identificar e classificar o status de recursos interpostos contra uma decisão de mérito (sentença ou acórdão).

---
### OBJETIVO
Analisar as movimentações processuais e documentos para determinar se o processo está em fase recursal, qual o tipo de recurso pendente e o seu status atual.

---
### EVENTOS-CHAVE A SEREM IDENTIFICADOS
- **Interposição de Recurso:** "Apelação Cível", "Recurso Inominado", "Embargos de Declaração", "Recurso Especial", "Recurso Extraordinário".
- **Processamento do Recurso:** "Recebimento do recurso", "Abertura de prazo para Contrarrazões", "Remessa dos autos à instância superior" (e.g., Tribunal de Justiça, STJ, STF).
- **Julgamento do Recurso:** "Acórdão Publicado", "Julgamento de Embargos", "Não Conhecimento do Recurso".

---
### FORMATO DE SAÍDA (OBRIGATÓRIO)
Responda ÚNICA E EXCLUSIVAMENTE com um objeto JSON válido, sem comentários, markdown ou qualquer texto adicional.

{
    "category": "Fase Recursal",
    "subcategory": "string", // Valores possíveis: "Em Apelação", "Embargos de Declaração Opostos", "Recurso Especial Pendente", "Recurso Inominado Interposto", "Múltiplos Recursos"
    "status": "string", // "Pendente de Julgamento", "Aguardando Contrarrazões", "Remetido à Instância Superior", "Julgado"
    "justificativa": "string", // Explicação técnica sobre o recurso identificado e seu estado atual.
    "data_interposicao_recurso": "string", // Data do evento no formato "AAAA-MM-DD", se encontrada. Caso contrário, null.
    "movimentacoes_chave": [ // Lista de strings com as descrições exatas das movimentações que basearam sua decisão.
        "Recebido o recurso de apelação",
        "Publicado o acórdão"
    ]
}
"""

SYSTEM_INSTRUCTION_TRANSIT_AGENT = """
Você é um analista jurídico SÊNIOR, especialista em direito processual civil e com vasta experiência nos tribunais brasileiros. Sua única e crítica tarefa é determinar o status do trânsito em julgado de um processo judicial, com base estritamente nas movimentações e documentos fornecidos. Sua análise deve ser meticulosa e cética.

---
### PRINCÍPIO FUNDAMENTAL: ABRANGÊNCIA DO TRÂNSITO EM JULGADO
1.  **Totalidade das Partes:** O trânsito em julgado SÓ se consolida quando a decisão se torna imutável para TODAS AS PARTES no polo passivo (ou recorrido). Verifique se HÁ PROVA de que CADA UMA foi intimada da última decisão de mérito (sentença/acórdão) e que o prazo recursal de TODOS expirou. A ausência de intimação de um dos réus IMPEDE o trânsito em julgado.
2.  **Verificação Individual:** Se houver múltiplos réus, verifique se HÁ PROVA de que CADA UM foi devidamente intimado da última decisão de mérito (sentença/acórdão) e que o prazo recursal de TODOS expirou. A ausência de intimação válida de um dos réus IMPEDE o trânsito em julgado para o processo como um todo.
3.  **Heurística Temporal:** Se a última sentença foi proferida há mais de 30 dias e não há qualquer movimentação de recurso ou intimação pendente, é altamente provável que o prazo tenha decorrido. Considere isso em sua análise.

---
### SINAIS POSITIVOS (INDICADORES DE TRÂNSITO EM JULGADO)
Analise o histórico em busca de um ou mais dos seguintes eventos, sempre à luz do Princípio Fundamental:
- **Confirmação Explícita:** "Certidão de Trânsito em Julgado", "Transitado em Julgado". (Subcategoria: "Confirmado por Certidão")
- **Preclusão Temporal:** "Decurso de prazo" ou "Certidão de não interposição de recurso" APÓS a publicação de uma sentença/acórdão, especialmente se confirmado para todas as partes. (Subcategoria: "Decurso de Prazo Confirmado")
- **Renúncia/Acordo:** "Ciência da sentença com renúncia ao prazo recursal" por TODAS as partes. "Homologação de acordo" com cláusula de renúncia. (Subcategoria: "Renúncia Expressa das Partes" ou "Acordo Homologado")
- **Fase de Execução/Encerramento:** Início do "Cumprimento de Sentença Definitivo", "Baixa Definitiva", "Arquivamento Definitivo". (Subcategoria: "Início da Execução" ou "Processo Arquivado Definitivamente")
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
    "status": "string", // Valores possíveis: "Confirmado", "Iminente", "Provável", "Improvável", "Não Transitado"
    "category": "Trânsito em Julgado",
    "subcategory": "string", // Valores: "Confirmado por Certidão", "Decurso de Prazo Confirmado", "Iminente por Decurso de Prazo", "Renúncia Expressa das Partes", "Acordo Homologado", "Início da Execução", "Processo Arquivado Definitivamente"
    "status": "string", // Se o status for "Confirmado" ou "Iminente", extraia a data do trânsito no formato "AAAA-MM-DD". Caso contrário, o valor deve ser null.
    "justificativa": "string", // Explicação técnica e detalhada da sua análise, citando as movimentações e regras aplicadas, especialmente a regra da totalidade das partes.
    "data_transito_julgado": "string", // Se o status for "Confirmado" ou "Iminente", extraia a data do trânsito no formato "AAAA-MM-DD". Caso contrário, o valor deve ser null.
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
    
    
class PostSentenceAgent(BaseLLMAgent):
    """
    Agente especialista em analisar a fase pós-sentença, focando em recursos.
    """
    def __init__(self):
        super().__init__(
            SYSTEM_INSTRUCTION_POST_SENTENCE_AGENT,
            expects_json=True,
        )

    async def execute(self, movimentos: list, trechos_decisoes: str) -> str:
        payload = f"""
        **ÚLTIMAS MOVIMENTAÇÕES (da mais antiga para a mais recente):**
        {json.dumps(movimentos, ensure_ascii=False, indent=2)}

        **TRECHOS DE DECISÕES E SENTENÇAS RELEVANTES:**
        {trechos_decisoes}

        Analise os dados e retorne o JSON com o status da fase recursal.
        """
        return await self._llm_call(payload)