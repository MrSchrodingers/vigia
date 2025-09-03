# vigia/departments/chatwoot_assistant/tools.py
from vigia.services.pipedrive_service import PipedriveService # Supondo que você tenha um serviço assim
import logging

# Instancia o serviço que de fato se comunica com a API do Pipedrive
pipedrive_service = PipedriveService()

async def get_deal_details_by_phone(phone: str) -> str:
    """
    Busca os detalhes de um negócio no Pipedrive associado a um número de telefone.
    Use esta função para obter informações sobre o negócio atual, como valor, etapa e produtos.
    """
    logging.info(f"Buscando detalhes do negócio para o telefone: {phone}")
    # LÓGICA DE IMPLEMENTAÇÃO:
    # 1. Chamar o pipedrive_service para encontrar a pessoa pelo telefone.
    # 2. Com o ID da pessoa, buscar os negócios associados.
    # 3. Retornar uma string formatada com os detalhes do negócio.
    # Por agora, retornamos um placeholder:
    return f"Placeholder: Detalhes do negócio para {phone} seriam buscados aqui."

async def add_note_to_deal(deal_id: int, note_content: str) -> str:
    """
    Adiciona uma nota a um negócio específico no Pipedrive.
    Use esta ferramenta para registrar informações importantes ou resumos da conversa diretamente no negócio.
    """
    logging.info(f"Adicionando nota ao negócio ID {deal_id}")
    # LÓGICA DE IMPLEMENTAÇÃO:
    # 1. Chamar o pipedrive_service para adicionar a nota ao deal_id especificado.
    # 2. Retornar uma confirmação.
    # Por agora, retornamos um placeholder:
    return f"Placeholder: Nota '{note_content}' seria adicionada ao negócio {deal_id}."

# Mapeamento de ferramentas para o orquestrador
AVAILABLE_TOOLS = {
    "get_deal_details_by_phone": get_deal_details_by_phone,
    "add_note_to_deal": add_note_to_deal,
}