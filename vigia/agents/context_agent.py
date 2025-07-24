import logging
from ..services import pipedrive_service

class PipedriveDataMinerAgent:
    """
    Agente Gerador: Focado exclusivamente em extrair dados brutos do Pipedrive.
    Não interpreta, apenas busca e retorna os dados como dicionários Python.
    """
    async def execute(self, conversation_jid: str) -> dict:
        logging.info(f"Minerador de Dados: Buscando dados para {conversation_jid}...")
        phone_number = conversation_jid.split('@')[0]
        
        person_info = await pipedrive_service.find_person_by_phone(phone_number)
        if not person_info:
            return {"person": None, "deal": None}

        deal_info = await pipedrive_service.find_deal_by_person_name(person_info["name"])
        
        return {"person": person_info, "deal": deal_info}

class ContextSynthesizerAgent:
    """
    Agente Validador/Refinador: Recebe dados brutos e os transforma em um
    resumo de contexto coeso e informativo.
    """
    def __init__(self):
        self.system_prompt = """
        Você é um analista de dados especialista em CRM. Sua tarefa é receber dados brutos
        do Pipedrive em formato de dicionário e criar um resumo textual conciso e claro
        chamado 'Contexto Adicional do CRM'. Se não houver dados, simplesmente declare isso.
        """

    async def execute(self, raw_data: dict) -> str:
        if not raw_data.get("person"):
            return "Nenhum contexto adicional encontrado no Pipedrive."

        person_name = raw_data["person"]["name"]
        deal_info = raw_data.get("deal")

        if not deal_info:
            return f"Contexto Adicional do CRM (Pipedrive):\n- Pessoa encontrada: {person_name} (ID: {raw_data['person']['id']}).\n- Nenhum deal associado encontrado."

        # Formata o contexto encontrado em uma string legível
        context_parts = [
            f"Contexto Adicional do CRM (Pipedrive) para {person_name}:",
            f"- Deal Encontrado: '{deal_info.get('title')}' (ID: {deal_info.get('id')})",
            f"- Valor do Deal: {deal_info.get('value')} {deal_info.get('currency')}",
            f"- Status Atual: {deal_info.get('status')}"
        ]
        
        if deal_info.get('notes'):
            # Filtra notas vazias e junta as restantes
            notes_str = " | ".join(note['content'] for note in deal_info['notes'] if note.get('content', '').strip())
            if notes_str:
                context_parts.append(f"- Notas do Deal: {notes_str}")
        
        logging.info("Síntese de contexto do Pipedrive concluída.")
        return "\n".join(context_parts)

data_miner_agent = PipedriveDataMinerAgent()
context_synthesizer_agent = ContextSynthesizerAgent()