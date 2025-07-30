from .specialist_agents import ExtractorAgent
from vigia.services import llm_service

_AUDIO_TOT_GUIDELINES = """
DIRETRIZES ÁUDIO (Tree-of-Thought + Confidence):
● Mensagens de áudio chegam como [ÁUDIO …].
● Se o texto contiver a palavra-chave “BAIXA”, marque a transcrição como potencialmente imprecisa.
● Proceda em três passos internos (NÃO revele):
  1) Gere hipóteses sobre números/datas/nomes citados.
  2) Verifique cada hipótese contra o contexto fornecido.
  3) Selecione as hipóteses que sobrevivem e produza o resultado final.
● Responda somente com JSON conforme o schema abaixo.
"""

AUDIO_JSON_SCHEMA = """
{
  "transcricao_limpa": "Transcrição já sem o rótulo [ÁUDIO] e sem ruídos.",
  "possui_baixa_confianca": "true se houver indício de confiabilidade baixa, senão false"
}
"""

class AudioTOTAgent(ExtractorAgent):
    def __init__(self):
        super().__init__(system_prompt=f"""
Você é um agente especialista em transcrição e interpretação de mensagens de voz em negociações.
Utilize raciocínio em Árvore (Tree-of-Thought) de forma oculta, seguindo as diretrizes abaixo,
e preencha o JSON exatamente com as chaves do schema.  
{_AUDIO_TOT_GUIDELINES}
Schema:
{AUDIO_JSON_SCHEMA}
""")
    
    async def execute(self, audio_payload: str, current_date: str) -> str:
        """
        Recebe SOMENTE o trecho “[ÁUDIO …] …” e devolve JSON com transcrição limpa.
        """
        user_prompt = f"""
        Considere que a data de hoje é {current_date}.
        A seguir, o conteúdo bruto do áudio:
        ---
        {audio_payload}
        ---
        Forneça o JSON solicitado, sem texto extra.
        """
        return await llm_service.llm_call(self.system_prompt, user_prompt)

audio_tot_agent = AudioTOTAgent()
