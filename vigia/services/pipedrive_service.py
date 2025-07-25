import logging
import httpx
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

from ..config import settings

logger = logging.getLogger(__name__)

class PipedriveClient:
    """
    Cliente HTTP assíncrono para a API V1 do Pipedrive.
    Cada instância é configurada com sua própria chave de API, permitindo
    o uso de múltiplas chaves em diferentes contextos (ex: WhatsApp, E-mail).
    """
    def __init__(self, api_token: str, base_url: str):
        if not api_token or not base_url:
            raise ValueError("API token e base URL são necessários para o PipedriveClient.")
        
        self.api_token = api_token
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=15.0, transport=httpx.AsyncHTTPTransport(retries=3))
        self.cache = {}
        self.cache_expiry = timedelta(minutes=5)

    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, json: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """Método genérico e centralizado para realizar requisições à API."""
        cache_key = f"{self.api_token}:{method}:{endpoint}:{str(params)}"
        if method.upper() == "GET" and cache_key in self.cache:
            if datetime.utcnow() < self.cache[cache_key]['expires_at']:
                logger.debug(f"Retornando do cache para a chave: {self.api_token[:5]}...")
                return self.cache[cache_key]['data']
            del self.cache[cache_key]

        url = f"{self.base_url}{endpoint}"
        request_params = {"api_token": self.api_token, **(params or {})}
        
        try:
            response = await self.client.request(method, url, params=request_params, json=json)
            response.raise_for_status()
            response_data = response.json()

            if response_data.get("success"):
                data_payload = response_data.get("data")
                if method.upper() == "GET" and data_payload is not None:
                    self.cache[cache_key] = {'data': data_payload, 'expires_at': datetime.utcnow() + self.cache_expiry}
                return data_payload
            
            logger.error(f"Erro na API Pipedrive: {response_data.get('error')}", extra={"url": url})
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro HTTP: {e.response.status_code} - {e.response.text}", extra={"url": url})
        except httpx.RequestError as e:
            logger.error(f"Erro de requisição: {e}", extra={"url": url})
        return None

    async def close(self):
        """Fecha a sessão do cliente httpx de forma elegante."""
        await self.client.aclose()

# --- Instâncias de Cliente por Departamento ---
whatsapp_client = PipedriveClient(
    api_token=settings.PIPEDRIVE_API_TOKEN_WHATSAPP, 
    base_url=settings.PIPEDRIVE_DOMAIN
)
email_client = PipedriveClient(
    api_token=settings.PIPEDRIVE_API_TOKEN_EMAIL, 
    base_url=settings.PIPEDRIVE_DOMAIN
)

# --- Funções Auxiliares de Formatação ---
def _sanitize_person_name(raw: str) -> str:
    """
    Remove dígitos e espaços/“+” excedentes do termo de pesquisa.

    Ex.:
        "  MAURICIO+CASTRO+08 " → "MAURICIO+CASTRO"
        "JOÃO  SILVA 123"     → "JOÃO  SILVA"
    """
    # 1. remove todos os números
    no_numbers = re.sub(r"\d+", "", raw)
    # 2. tira espaços em excesso
    trimmed = no_numbers.strip()
    # 3. remove "+" só se estiver no começo ou fim (evita '...+08' ficar com '+')
    trimmed = trimmed.strip("+")
    # 4. colapsa múltiplos "+" consecutivos (opcional, se for útil)
    return re.sub(r"\++", "+", trimmed)

def clean_phone(raw: str) -> str:
    """
    Normaliza números BR (móvel) para o formato **AA9XXXXXXXX**
    ─ remove qualquer coisa que não seja dígito
    ─ remove o prefixo internacional 55, se existir
    ─ se restarem 10 dígitos (AAXXXXXXXX) insere o 9 logo
      depois do DDD, resultando em 11 dígitos
    """
    # 1 – só dígitos
    digits = re.sub(r"\D", "", raw)

    # 2 – tira o +55 (ou 0055) se presente
    if digits.startswith("55"):
        digits = digits[2:]

    # 3 – se ficou com 10 dígitos, é porque falta o 9
    #     → AA + 9 + XXXXXXXX
    if len(digits) == 10:
        digits = digits[:2] + "9" + digits[2:]

    # 4 – devolve do jeito que o WhatsApp gosta: 11 dígitos
    return digits

def _format_deal_details(data: Dict[str, Any]) -> Dict[str, Any]:
    """Formata a resposta detalhada de um deal em um dicionário limpo e útil."""
    if not data: 
        return {}
    custom_fields = {k: v for k, v in data.items() if re.match(r'^[0-9a-f]{40}$', k)}
    return {
        "id": data.get("id"), "title": data.get("title"), "value": data.get("value"),
        "formatted_value": data.get("formatted_value"), "currency": data.get("currency"),
        "status": data.get("status"), "person_id": data.get("person_id", {}).get("value"),
        "person_name": data.get("person_name"), "owner_name": data.get("owner_name"),
        "stage_id": data.get("stage_id"), "pipeline_id": data.get("pipeline_id"),
        "notes": [], "add_time": data.get("add_time"), "update_time": data.get("update_time"),
        "won_time": data.get("won_time"), "lost_time": data.get("lost_time"),
        "next_activity_subject": data.get("next_activity_subject"),
        "next_activity_date": data.get("next_activity_date"), "custom_fields": custom_fields
    }

def _format_person_details(data: Dict[str, Any]) -> Dict[str, Any]:
    """Formata a resposta detalhada de uma pessoa em um dicionário limpo."""
    if not data: 
        return {}
    return {
        "id": data.get("id"), "name": data.get("name"), "owner_name": data.get("owner_name"),
        "phones": [p.get("value") for p in data.get("phone", []) if p.get("value")],
        "emails": [e.get("value") for e in data.get("email", []) if e.get("value")],
        "organization_name": data.get("org_name"), "open_deals_count": data.get("open_deals_count", 0),
        "update_time": data.get("update_time"),
    }

# --- Funções de Serviço Genéricas (usam um cliente injetado) ---
async def find_person_by_id(client: PipedriveClient, person_id: int) -> Optional[Dict[str, Any]]:
    """Busca e formata os detalhes de uma pessoa pelo seu ID."""
    logger.debug(f"Buscando detalhes da pessoa por ID: {person_id}")
    data = await client._request("GET", f"/persons/{person_id}")
    return _format_person_details(data)

async def find_deal_by_id(client: PipedriveClient, deal_id: int) -> Optional[Dict[str, Any]]:
    """Busca e formata os detalhes de um deal pelo seu ID, incluindo suas notas."""
    logger.debug(f"Buscando detalhes do deal por ID: {deal_id}")
    data = await client._request("GET", f"/deals/{deal_id}")
    if not data: 
        return None
    
    formatted_deal = _format_deal_details(data)
    notes_data = await client._request("GET", f"/deals/{deal_id}/notes")
    if notes_data:
        formatted_deal["notes"] = [note.get("content", "") for note in notes_data]
    return formatted_deal

async def find_person_by_phone(client: PipedriveClient, phone: str) -> Optional[Dict[str, Any]]:
    """Busca uma pessoa pelo telefone e retorna seus detalhes completos."""
    logger.debug(f"Buscando pessoa por telefone: {clean_phone(phone)}")
    params = {"term": clean_phone(phone), "fields": "phone,custom_fields", "search_for_related_items": 1}
    data = await client._request("GET", "/persons/search", params=params)
    
    items = data.get("items", []) if data else []
    if items:
        person_id = items[0].get("item", {}).get("id")
        if person_id:
            return await find_person_by_id(client, person_id)
    return None

async def find_person_by_email(client: PipedriveClient, email: str) -> Optional[Dict[str, Any]]:
    """Busca uma pessoa pelo e-mail e retorna seus detalhes completos."""
    logger.debug(f"Buscando pessoa por e-mail: {email}")
    params = {"term": email, "fields": "email", "exact_match": True}
    data = await client._request("GET", "/persons/search", params=params)

    items = data.get("items", []) if data else []
    if items:
        person_id = items[0].get("item", {}).get("id")
        if person_id:
            return await find_person_by_id(client, person_id)
    return None

async def find_deal_by_person_name(
    client: "PipedriveClient",
    person_name: str
) -> Optional[Dict[str, Any]]:
    """
    Busca um deal pelo nome da pessoa no título, após sanitizar o termo.
    """
    clean_name = _sanitize_person_name(person_name)
    logger.debug("Buscando deal por nome de pessoa: '%s' (sanitizado de '%s')",
                 clean_name, person_name)

    params = {"term": clean_name, "fields": "title"}
    data = await client._request("GET", "/deals/search", params=params)

    for item in data.get("items", []):
        deal_id = item.get("item", {}).get("id")
        if deal_id:
            return await find_deal_by_id(client, deal_id)
    return None

async def find_deal_by_term(client: PipedriveClient, search_term: str, search_fields: list[str]) -> Optional[Dict[str, Any]]:
    """
    Busca um deal por um termo em uma lista de campos especificados e retorna seus detalhes completos.
    """
    logger.debug(f"Buscando deal por termo '{search_term}' nos campos {search_fields}")
    params = {"term": search_term, "fields": ",".join(search_fields)}
    data = await client._request("GET", "/deals/search", params=params)

    items = data.get("items", []) if data else []
    if items:
        # Pega o item com a maior pontuação de resultado (mais relevante)
        best_match = max(items, key=lambda x: x.get('result_score', 0))
        deal_id = best_match.get("item", {}).get("id")
        if deal_id:
            return await find_deal_by_id(client, deal_id)
    return None

async def create_activity(
    client: PipedriveClient,
    person_id: int,
    due_date: str,
    note_summary: str,
    deal_id: Optional[int] = None,
    subject: str = "Follow-up de Negociação"
) -> Optional[Dict[str, Any]]:
    """
    Cria uma nova atividade (tarefa) no Pipedrive usando o cliente especificado.
    """
    logger.info(f"Criando atividade para a pessoa ID {person_id} usando a chave: {client.api_token[:5]}...")
    try:
        valid_date = datetime.fromisoformat(due_date.replace("Z", "+00:00")).strftime('%Y-%m-%d')
    except (ValueError, AttributeError):
        logger.error(f"Formato de data inválido para atividade: '{due_date}'. Use AAAA-MM-DD.")
        return {"error": f"Data inválida: {due_date}. Use o formato AAAA-MM-DD."}

    payload = {
        "subject": subject,
        "type": "task",
        "due_date": valid_date,
        "person_id": person_id,
        "note": note_summary,
    }
    if deal_id:
        payload["deal_id"] = deal_id

    return await client._request("POST", "/activities", json=payload)