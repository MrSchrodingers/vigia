import json
from .base_llm_agent import BaseLLMAgent

### 2.1 Assunto #############################################################
class SubjectDataExtractorAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Extraia "numero_processo" (regex \\d{7}-\\d{2}\\.\\d{4}\\.\\d\\.\\d{2}\\.\\d{4})
        e "nome_parte" (texto após "PARTE:").
        Retorne somente JSON {"numero_processo": str|null, "nome_parte": str|null}.
        """
        few_shot = '''
        Input: "RES: PROPOSTA DE ACORDO – 0004784-62.2025.8.16.0021 - PARTE: EDIMAR KAMIEN"
        Output: {"numero_processo":"0004784-62.2025.8.16.0021", "nome_parte":"EDIMAR KAMIEN"}
        '''
        super().__init__(specific_prompt, few_shot)

    async def execute(self, subject: str) -> str:
        return await self._llm_call(subject)

### 2.2 Legal/Financeiro ####################################################
class LegalFinancialSpecialistAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Extraia JSON:
        {
          "proposta": {
              "proposta_valor": str|null,
              "proposta_prazo": str|null,
              "condicoes": list[str]
          },
          "argumentos_legais": list[str],
          "status_acordo": str|null
        }
        * Valores monetários: inclua "R$" + números encontrados primeiro.
        * Prazo: busque "dia", "dias", "úteis", "parcel" etc.
        * Condições: array de sentenças encontradas com "pagamento", "conta", "assinatura"…
        """
        super().__init__(specific_prompt)

    async def execute(self, email_body: str) -> str:
        return await self._llm_call(email_body)

### 2.3 Stage ###############################################################
class NegotiationStageSpecialistAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Classifique "estagio_negociacao" em:
        ["Proposta Inicial","Contraproposta","Esclarecimento de Dúvidas",
         "Acordo Fechado","Negociação Estagnada","Acordo Rejeitado"].
        Classifique "tom_da_conversa":
        ["Colaborativo","Neutro","Hostil","Urgente"].
        Retorne {"estagio_negociacao": str, "tom_da_conversa": str}.
        """
        super().__init__(specific_prompt)

    async def execute(self, email_body: str) -> str:
        return await self._llm_call(email_body)

### 2.4 Comportamental ######################################################
class EmailBehavioralAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Com base nos metadados JSON, gere:
        {
          "engajamento": int 0‑10,
          "urgencia": int 0‑10,
          "resumo_comportamental": str
        }
        • importance=="high" → +4 urgencia
        • has_attachments==True → +2 engajamento
        • reply_latency_sec<3600 → +3 engajamento
        Normalize p/ faixa 0‑10 (cap).
        """
        super().__init__(specific_prompt)

    async def execute(self, metadata_json: dict[str, any]) -> str:
        return await self._llm_call(json.dumps(metadata_json, ensure_ascii=False, indent=2))
