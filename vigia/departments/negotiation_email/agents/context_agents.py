
import logging
import re
from typing import Dict, Any, Tuple, Optional

from vigia.services import pipedrive_service
from vigia.services.pipedrive_service import email_client
from vigia.departments.negotiation_whatsapp.agents.context_agent import ContextSynthesizerAgent

logger = logging.getLogger(__name__)

class EmailDataMinerAgent:
    """
    Agente Gerador para E-mail (Lógica Invertida e Otimizada):
    1.  Extrai o número do processo do assunto do e-mail.
    2.  Usa este número como chave primária para buscar o Deal via campo customizado.
    3.  Se o Deal for encontrado, utiliza o 'person_id' associado a ele para buscar 
        os detalhes completos da Pessoa.
    4.  Este método é mais preciso e eficiente, pois o número do processo é um 
        identificador forte e único.
    """
    @staticmethod
    def _extract_info_from_subject(subject: str) -> Tuple[Optional[str], Optional[str]]:
        """Extrai o número do processo e o nome da parte do assunto do e-mail."""
        lawsuit_number, party_name = None, None

        # Tenta extrair o número do processo
        lawsuit_match = re.search(r'(\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4})', subject)
        if lawsuit_match:
            lawsuit_number = lawsuit_match.group(1)

        # Tenta extrair o nome da parte, que geralmente está entre "PARTE:" e um possível " - "
        party_match = re.search(r'PARTE:\s*(.*?)(?:\s*-\s*GRUPO|\s*$)', subject, re.IGNORECASE)
        if party_match:
            party_name = party_match.group(1).strip()
            
        return lawsuit_number, party_name

    async def execute(self, subject: str) -> Dict[str, Any]:
        logger.info(f"Minerador (E-mail): Iniciando busca com o assunto: '{subject}'")
        lawsuit_number, party_name = self._extract_info_from_subject(subject)
        
        deal_details = None
        
        # --- Busca Primária: Pelo número do processo ---
        if lawsuit_number:
            logger.info(f"Busca primária com número do processo: {lawsuit_number}")
            deal_details = await pipedrive_service.find_deal_by_term(
                client=email_client, 
                search_term=lawsuit_number, 
                search_fields=["custom_fields"]
            )

        # --- Busca Fallback: Pelo nome da parte (se a primária falhou e o nome existe) ---
        if not deal_details and party_name:
            logger.warning(f"Busca primária falhou. Ativando fallback com nome da parte: '{party_name}'")
            deal_details = await pipedrive_service.find_deal_by_term(
                client=email_client, 
                search_term=party_name, 
                search_fields=["title"]
            )
            
        if not deal_details:
            logger.error("Não foi possível encontrar um deal correspondente para o assunto.")
            return {"person": None, "deal": None}
        
        logger.info(f"Deal ID {deal_details.get('id')} encontrado.")

        # --- Busca da Pessoa ---
        person_id = deal_details.get("person_id")
        if not person_id:
            logger.error(f"O Deal ID {deal_details.get('id')} não tem uma pessoa associada.")
            return {"person": None, "deal": deal_details}
            
        person_details = await pipedrive_service.find_person_by_id(email_client, person_id)
        if not person_details:
            logger.error(f"Não foi possível encontrar a Pessoa ID {person_id}.")
            return {"person": None, "deal": deal_details}

        logger.info(f"Pessoa ID {person_details.get('id')} encontrada.")
        return {"person": person_details, "deal": deal_details}

# --- Instanciando os Agentes ---
data_miner_agent = EmailDataMinerAgent()
context_synthesizer_agent = ContextSynthesizerAgent()