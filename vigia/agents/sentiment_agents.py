from ..services import llm_service

class SentimentAnalysisAgent:
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt

    async def execute(self, conversation_history: str) -> str:
        user_prompt = f"""
        Analise o histórico da conversa de negociação abaixo.

        Histórico da Conversa:
        ---
        {conversation_history}
        ---

        Sua Análise de Sentimento:
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

# FUNCIONÁRIO 1: O Analista Lexical
lexical_sentiment_agent = SentimentAnalysisAgent(
    system_prompt="""
    Você é um analista de sentimento focado em análise lexical.
    Analise o texto e classifique o sentimento predominante do CLIENTE como 'Positivo', 'Neutro', 'Negativo' ou 'Crítico'.
    Baseie sua análise APENAS nas palavras, gírias, emojis e pontuação usados.
    Responda em JSON com as chaves 'sentimento_lexical' e 'justificativa_lexical'.
    Exemplo: {"sentimento_lexical": "Negativo", "justificativa_lexical": "Cliente usou as palavras 'absurdo' e 'problema'."}
    """
)

# FUNCIONÁRIO 2: O Analista Comportamental
behavioral_sentiment_agent = SentimentAnalysisAgent(
    system_prompt="""
    Você é um analista de sentimento focado em análise comportamental.
    IGNORE AS PALAVRAS. Analise o padrão de comunicação do CLIENTE.
    Classifique o sentimento como 'Positivo', 'Neutro', 'Negativo' ou 'Crítico'.
    Considere: uso de caixa alta, frequência das mensagens, repetição, agressividade na velocidade da resposta.
    Responda em JSON com as chaves 'sentimento_comportamental' e 'justificativa_comportamental'.
    Exemplo: {"sentimento_comportamental": "Crítico", "justificativa_comportamental": "Cliente está enviando múltiplas mensagens curtas em caixa alta, indicando urgência e frustração."}
    """
)

# O GESTOR do Departamento de Temperatura
class SentimentManagerAgent:
    def __init__(self):
        self.system_prompt = """
        Você é um experiente Gerente de Customer Experience (CX). Sua função é
        sintetizar análises de sentimento para determinar a real temperatura de uma conversa.
        Responda APENAS com um objeto JSON.
        """

    async def execute(self, lexical_analysis: str, behavioral_analysis: str) -> str:
        # GoT Prompt: Sintetiza dois pontos de vista diferentes em uma conclusão final.
        user_prompt = f"""
        Seus analistas produziram os seguintes relatórios de sentimento sobre uma conversa:

        1. Análise Lexical (baseada em palavras):
        {lexical_analysis}

        2. Análise Comportamental (baseada em padrões):
        {behavioral_analysis}

        Com base em AMBAS as análises, determine a 'temperatura' final da conversa.
        As opções são: 'Positivo', 'Neutro', 'Negativo', 'Crítico'.
        'Crítico' é mais urgente que 'Negativo'.
        Forneça uma justificativa final que combine os insights.
        Responda com um JSON contendo 'temperatura_final' e 'justificativa_final'.
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

sentiment_manager_agent = SentimentManagerAgent()