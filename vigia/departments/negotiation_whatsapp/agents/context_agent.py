import logging
from typing import Dict, Any

from vigia.services import pipedrive_service
from vigia.services.pipedrive_service import whatsapp_client

class PipedriveDataMinerAgent:
    """
    Agente Gerador para WhatsApp: Busca os dados mais ricos possíveis a partir de um telefone.
    """
    async def execute(self, conversation_jid: str) -> Dict[str, Any]:
        phone_number = conversation_jid.split('@')[0]
        logging.info(f"Minerador (WhatsApp): Buscando dados para {phone_number}...")

        person_details = await pipedrive_service.find_person_by_phone(whatsapp_client, phone_number)
        
        if not person_details:
            return {"person": None, "deal": None}

        deal_details = await pipedrive_service.find_deal_by_person_name(whatsapp_client, person_details["name"])
        return {"person": person_details, "deal": deal_details}

class ContextSynthesizerAgent:
    """
    Agente Sintetizador: Transforma os dados ricos do Pipedrive em um resumo textual
    detalhado para dar contexto aos agentes de análise.
    """
    async def execute(self, raw_data: Dict[str, Any]) -> str:
        person = raw_data.get("person")
        deal = raw_data.get("deal")

        if not person:
            return "Nenhum contexto encontrado no Pipedrive."

        person_name = person.get("name", "N/A")
        context_parts = [f"**Contexto do CRM (Pipedrive) para {person_name}**"]
        
        context_parts.append(f"- **Pessoa:** {person_name} (ID: {person.get('id')})")
        if person.get("owner_name"):
            context_parts.append(f"  - Responsável pela Pessoa: {person.get('owner_name')}")
        if person.get("emails"):
            context_parts.append(f"  - E-mails: {', '.join(person['emails'])}")
        
        if deal:
            context_parts.append(f"- **Negócio:** '{deal.get('title')}' (ID: {deal.get('id')})")
            if deal.get("owner_name"):
                context_parts.append(f"  - Responsável pelo Negócio: {deal.get('owner_name')}")
            context_parts.append(f"  - Status: **{deal.get('status', 'N/A').upper()}**")
            context_parts.append(f"  - Valor: {deal.get('formatted_value', 'N/A')}")
            if deal.get("won_time"):
                context_parts.append(f"  - Data de Sucesso: {deal['won_time']}")
            if deal.get("next_activity_subject"):
                context_parts.append(f"  - Próxima Atividade: '{deal['next_activity_subject']}' em {deal.get('next_activity_date', 'N/A')}")
            if deal.get('notes'):
                notes_str = " | ".join(deal['notes'])
                context_parts.append(f"  - Notas Importantes: {notes_str}")
        else:
            context_parts.append("- **Negócio:** Nenhum negócio associado foi encontrado.")
        
        logging.info("Síntese de contexto aprimorada concluída.")
        return "\n".join(context_parts)

data_miner_agent = PipedriveDataMinerAgent()
context_synthesizer_agent = ContextSynthesizerAgent()