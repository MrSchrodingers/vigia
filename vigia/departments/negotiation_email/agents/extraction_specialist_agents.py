from vigia.services import llm_service

class SubjectDataExtractorAgent:
    """Especialista #1: Focado em extrair dados estruturados SOMENTE do assunto do e-mail."""
    def __init__(self):
        self.system_prompt = """
        Sua única tarefa é extrair o número do processo e o nome da parte do assunto de um e-mail.
        O nome da parte geralmente vem depois de "PARTE:".
        Retorne APENAS um objeto JSON com as chaves "numero_processo" e "nome_parte".
        Se uma informação não for encontrada, retorne null para essa chave.

        Input: "RES: PROPOSTA DE ACORDO: 0004784-62.2025.8.16.0021 - PARTE: EDIMAR KAMIEN"
        Output:
        {
            "numero_processo": "0004784-62.2025.8.16.0021",
            "nome_parte": "EDIMAR KAMIEN"
        }
        """
    async def execute(self, subject: str) -> str:
        return await llm_service.llm_call(self.system_prompt, subject)

class LegalFinancialSpecialistAgent:
    """Especialista #2: Analisa o CORPO do e-mail em busca de termos jurídicos e financeiros."""
    def __init__(self):
        self.system_prompt = """
        Você é um analista paralegal sênior com foco em finanças. Analise o corpo da thread de e-mails.
        Sua missão é extrair:
        1.  Dados da Proposta: Qualquer valor monetário (proposta_valor), prazo para pagamento (proposta_prazo) e condições (ex: parcelamento, à vista).
        2.  Argumentos Jurídicos: Principais argumentos usados pela outra parte (ex: "cita o artigo 5", "alega hipossuficiência").
        3.  Status do Acordo: A proposta foi aceita, rejeitada ou está em negociação?

        Retorne APENAS um objeto JSON com as chaves "proposta", "argumentos_legais" e "status_acordo".
        """
    async def execute(self, email_body: str) -> str:
        return await llm_service.llm_call(self.system_prompt, email_body)

class NegotiationStageSpecialistAgent:
    """Especialista #3: Identifica o estágio e o tom da negociação a partir do corpo do e-mail."""
    def __init__(self):
        self.system_prompt = """
        Você é um especialista em comunicação. Analise a conversa e identifique o estágio atual da negociação.
        Estágios possíveis: "Proposta Inicial", "Contraproposta", "Esclarecimento de Dúvidas", "Acordo Fechado", "Negociação Estagnada", "Acordo Rejeitado".
        Identifique também o "tom_da_conversa" (ex: "Colaborativo", "Hostil", "Neutro", "Urgente").

        Retorne APENAS um objeto JSON com as chaves "estagio_negociacao" e "tom_da_conversa".
        """
    async def execute(self, email_body: str) -> str:
        return await llm_service.llm_call(self.system_prompt, email_body)