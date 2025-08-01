
from typing import Dict, Any

# Mapeamento de ID para Nome do Pipeline
PIPELINE_MAP = {
    9: "Trabalhista - Localização",
    10: "Trabalhista - Negociação",
    12: "1-INDENIZATÓRIA - ANÁLISE",
    13: "2-INDENIZATÓRIA - NEGOCIAÇÃO",
    15: "0-INDENIZATORIA - FORA DA BASE",
    16: "4-INDENIZATORIA_FECHAMENTO"
}

# Mapeamento de ID para Nome do Stage
STAGE_MAP = {
    92: "Não localizado",
    93: "Localizado/Solicitado cálculo",
    96: "Em Negociação",
    97: "Enviar contraproposta Bco",
    98: "Proibido acordo",
    100: "Recusado/Sem interesse",
    101: "Acordo Fechado",
    104: "Cálculo recepcionado",
    105: "Retorno Contra./Negociação",
    106: "Dúvida advogado",
    107: "DÚVIDAS",
    109: "PROIBIDO ACORDO",
    118: "ELEGÍVEIS - CÁLCULO",
    119: "NÃO LOCALIZADO",
    122: "EM NEGOCIAÇÃO",
    123: "ENVIADO CONTRAPROPOSTA",
    124: "RECUSADO",
    126: "COLHER ASSINATURA",
    128: "ELEGÍVEIS - NEGOCIADOR",
    135: "AGUARDANDO ALCADA DO BANCO",
    136: "Contato Realizado",
    137: "PROIBIDO ACORDO",
    138: "DUVIDA",
    139: "RECUSADO",
    140: "NEGOCIAÇÃO QUENTE",
    
    141: "ELABORAR MINUTA (Amanda)",
    143: "ACORDO EM AUDIENCIA",
    145: "PARA PROTOCOLO",
    146: "AGUARDANDO REGULARIZACAO",
    147: "BAIXADO POR ACORDO",
    148: "PAGAMENTO SOLICITADO",
    
    149: "INICIAR NEGOCIAÇÃO",
    150: "ENVIADO E-MAIL"
}

CUSTOM_FIELD_KEYS = {
    "valor_do_acordo": "4227f47064ecbd933c9452f49feea489a04d43e1"
}

def enrich_deal_with_context(deal_details: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recebe um dicionário de detalhes de um negócio e adiciona os nomes
    do pipeline e do stage com base em seus IDs.
    """
    if not deal_details:
        return {}

    pipeline_id = deal_details.get("pipeline_id")
    stage_id = deal_details.get("stage_id")

    # Adiciona o nome do pipeline, se o ID for encontrado no mapa
    if pipeline_id in PIPELINE_MAP:
        deal_details["pipeline_name"] = PIPELINE_MAP[pipeline_id]

    # Adiciona o nome do stage, se o ID for encontrado no mapa
    if stage_id in STAGE_MAP:
        deal_details["stage_name"] = STAGE_MAP[stage_id]

    return deal_details