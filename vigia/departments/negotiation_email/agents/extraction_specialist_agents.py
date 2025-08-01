import json
from .base_llm_agent import BaseLLMAgent

### 2.1 Assunto #############################################################
class SubjectDataExtractorAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Você é um especialista em analisar assuntos de e-mail de natureza jurídica para extrair dados chave. Os formatos variam, então preste muita atenção ao contexto.

        Sua tarefa é extrair "numero_processo" e "nome_parte" e normalizá-los.

        **Regras de Extração:**

        1.  **Para "numero_processo":**
            - Procure por um número no formato `NNNNNNN-NN.YYYY.J.TR.OOOO` (ex: `0003122-49.2025.8.16.0058`).
            - Se não encontrar, procure por uma sequência de 20 dígitos contínuos (ex: `50067295820258240091`).
            - **IMPORTANTE:** Após extrair o número, **normalize-o SEMPRE** para o formato com 20 dígitos contínuos, removendo todos os pontos, traços e espaços.

        2.  **Para "nome_parte":**
            - A "parte" é sempre um nome de pessoa, não de empresa (ignore "BRADESCO", "GRUPO BRADESCO", etc.).
            - Primeiro, procure pelo marcador "PARTE:". Se encontrar, extraia o nome que vem a seguir.
            - Se não houver o marcador "PARTE:", identifique o nome próprio da pessoa que aparece no assunto. Ele pode estar antes ou depois do número do processo.
            - Se nenhum nome de pessoa for claramente identificável, retorne `null`.

        Retorne **APENAS** um objeto JSON com a estrutura:
        `{"numero_processo": "string_20_digitos | null", "nome_parte": "string | null"}`
        """
        
        # Exemplos abrangentes para ensinar o modelo a lidar com a variabilidade.
        few_shot = '''
        Input: "PROPOSTA DE ACORDO: 0003122-49.2025.8.16.0058 - PARTE: ALBERTO BARRADAS MARQUES - GRUPO BRADESCO."
        Output: {"numero_processo": "00031224920258160058", "nome_parte": "ALBERTO BARRADAS MARQUES"}
        
        Input: "PROPOSTA DE ACORDO - Volnei Rodrigues Da Silva De Oliveira - 5001572-37.2025.8.24.0081 - BRADESCO"
        Output: {"numero_processo": "50015723720258240081", "nome_parte": "Volnei Rodrigues Da Silva De Oliveira"}

        Input: "PROPOSTA DE ACORDO - ANNA CHRISTINA VIEIRA - 50067295820258240091"
        Output: {"numero_processo": "50067295820258240091", "nome_parte": "ANNA CHRISTINA VIEIRA"}
        
        Input: "PROPOSTA DE ACORDO - BRADESCO 0002076-06.2024.8.16.0108 - CLARICE DA SILVA VIEIRA"
        Output: {"numero_processo": "00020760620248160108", "nome_parte": "CLARICE DA SILVA VIEIRA"}

        Input: "RES: Proposta de Acordo AUTOS Nº 5011350-60.2025.8.24.0039"
        Output: {"numero_processo": "50113506020258240039", "nome_parte": null}
        '''
        super().__init__(specific_prompt, few_shot)

    async def execute(self, subject: str) -> str:
        return await self._llm_call(subject)
    
### 2.2 Legal/Financeiro ####################################################
class LegalFinancialSpecialistAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Você é um analista jurídico especializado em ler trocas de e-mail de negociação e diferenciar os argumentos de cada parte.
        Sua tarefa é extrair os dados financeiros e os argumentos, atribuindo-os corretamente a 'Nós' e ao 'Cliente'.

        **INSTRUÇÕES IMPORTANTES:**
        1.  O texto já foi pré-processado. Foque no conteúdo da conversa.
        2.  Identifique o remetente ("De:") de cada mensagem para atribuir os argumentos.
        3.  Mensagens enviadas por endereços de '@amaralvasconcellos.com.br' ou '@pavcob.com.br' são **NOSSOS** argumentos.
        4.  Todas as outras mensagens são argumentos do **CLIENTE**.
        5.  A "proposta_atual" deve ser a última oferta válida que está na mesa, independentemente de quem a fez.

        Retorne **APENAS** um objeto JSON com a seguinte estrutura:
        {
          "proposta_atual": {
            "valor": "string | null",
            "prazo": "string | null",
            "condicoes": ["string"]
          },
          "argumentos_nossos": ["string"],
          "argumentos_cliente": ["string"],
          "status_acordo": "string | null"
        }
        """
        super().__init__(specific_prompt)

    async def execute(self, email_body: str) -> str:
        return await self._llm_call(email_body)

### 2.3 Stage ###############################################################
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

### 2.4 Comportamental ######################################################
class EmailBehavioralAgent(BaseLLMAgent):
    def __init__(self):
        specific_prompt = """
        Com base nos metadados JSON, gere:
        {
          "engajamento": int 0-10,
          "urgencia": int 0-10,
          "resumo_comportamental": str
        }
        • importance=="high" → +4 urgencia
        • has_attachments==True → +2 engajamento
        • reply_latency_sec<3600 → +3 engajamento
        Normalize p/ faixa 0-10 (cap).
        """
        super().__init__(specific_prompt)

    async def execute(self, metadata_json: dict[str, any]) -> str:
        return await self._llm_call(json.dumps(metadata_json, ensure_ascii=False, indent=2))
