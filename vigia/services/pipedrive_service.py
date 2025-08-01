import logging
import httpx
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import asyncio
from collections import deque
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_exception
from vigia.departments.negotiation_email.utils.pipedrive_context_mapper import CUSTOM_FIELD_KEYS

from ..config import settings

logger = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (
    httpx.RequestError,
    httpx.HTTPStatusError,
)

def _is_retryable_status(e: BaseException) -> bool:
    """Verifica se o status HTTP da exceção é um que justifique uma nova tentativa."""
    if isinstance(e, httpx.HTTPStatusError):
        status_code = e.response.status_code
        # 5xx para erros de servidor, 429 para limite de taxa
        return status_code >= 500 or status_code == 429
    return True # Para outros erros de requisição (ex: timeout)

class PipedriveClient:
    """
    Cliente HTTP assíncrono e otimizado para a API V1 do Pipedrive.
    
    Funcionalidades:
    - Retry inteligente com backoff exponencial para erros de rede e API.
    - Rate Limiting para evitar bloqueios por excesso de requisições.
    - Cache em memória para requisições GET.
    - Suporte a gerenciamento de contexto (`async with`).
    """
    def __init__(self, api_token: str, base_url: str, requests_per_second: int = 2):
        if not api_token or not base_url:
            raise ValueError("API token e base URL são necessários para o PipedriveClient.")
        
        self.api_token = api_token
        self.base_url = base_url.rstrip('/')
        self.client = httpx.AsyncClient(timeout=20.0) # Timeout um pouco maior
        
        # Cache
        self.cache = {}
        self.cache_expiry = timedelta(minutes=5)
        
        # Rate Limiting
        self.rate_limit_interval = 1.0 / requests_per_second
        self.request_timestamps = deque()

    @retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS) & retry_if_exception(_is_retryable_status),
        wait=wait_exponential(multiplier=1, min=2, max=10), # Espera 2s, 4s, 8s...
        stop=stop_after_attempt(3),
        before_sleep=lambda retry_state: logger.warning(
            f"Tentativa {retry_state.attempt_number} falhou. Tentando novamente em {retry_state.next_action.sleep:.2f}s..."
        )
    )
    async def _request(self, method: str, endpoint: str, params: Optional[Dict] = None, json: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """Método genérico para realizar requisições, com retry, cache e rate limiting."""
        # 1. Checagem do Cache (apenas para GET)
        cache_key = f"{self.api_token[-5:]}:{method}:{endpoint}:{str(params)}"
        if method.upper() == "GET" and cache_key in self.cache:
            if datetime.utcnow() < self.cache[cache_key]['expires_at']:
                logger.debug(f"Retornando do cache para a chave: {self.api_token[-5:]}...")
                return self.cache[cache_key]['data']
            del self.cache[cache_key]

        # 2. Rate Limiting
        now = datetime.utcnow().timestamp()
        while self.request_timestamps and now - self.request_timestamps[0] < 1.0:
            if len(self.request_timestamps) >= int(1.0 / self.rate_limit_interval):
                await asyncio.sleep(self.rate_limit_interval)
            else:
                break
            now = datetime.utcnow().timestamp()
        self.request_timestamps.append(now)
        if len(self.request_timestamps) > int(1.0 / self.rate_limit_interval):
             self.request_timestamps.popleft()
        
        # 3. Execução da Requisição
        url = f"{self.base_url}{endpoint}"
        request_params = {"api_token": self.api_token, **(params or {})}
        
        logger.debug(f"Executando {method} para {url} com params: {request_params}")
        response = await self.client.request(method, url, params=request_params, json=json)
        response.raise_for_status() # Lança exceção para códigos de erro (4xx, 5xx)
        response_data = response.json()

        if response_data.get("success"):
            data_payload = response_data.get("data")
            if method.upper() == "GET" and data_payload is not None:
                self.cache[cache_key] = {'data': data_payload, 'expires_at': datetime.utcnow() + self.cache_expiry}
            return data_payload
        
        logger.error(f"Erro na API Pipedrive: {response_data.get('error')}", extra={"url": url})
        return None

    async def close(self):
        """Fecha a sessão do cliente httpx de forma elegante."""
        await self.client.aclose()

    async def __aenter__(self):
        """Permite o uso com 'async with'."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Garante que o cliente seja fechado ao sair do bloco 'async with'."""
        await self.close()

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
    """Remove dígitos e espaços/“+” excedentes do termo de pesquisa."""
    no_numbers = re.sub(r"\d+", "", raw)
    trimmed = no_numbers.strip().strip("+")
    return re.sub(r"\s*\+\s*", "+", trimmed)

def _generate_phone_variations(phone: str) -> list[str]:
    """
    A partir de um número de telefone limpo (10 ou 11 dígitos), gera variações formatadas.
    Ex: '11987654321' -> ['11 98765-4321']
    Ex: '1187654321'  -> ['11 8765-4321']
    """
    variations = []
    if len(phone) == 11 and phone[2] == '9': # Celular com 9º dígito
        # Formato: 11 98765-4321
        variations.append(f"{phone[:2]} {phone[2:7]}-{phone[7:]}")
    elif len(phone) == 10: # Fixo ou celular antigo
        # Formato: 11 8765-4321
        variations.append(f"{phone[:2]} {phone[2:6]}-{phone[6:]}")
    return variations

def _clean_phone(raw_phone: str) -> str:
    """
    Normaliza um número de telefone brasileiro para o Pipedrive.
    - Remove caracteres não numéricos.
    - Remove o código de país '55' se presente.
    - Adiciona o nono dígito '9' para celulares com 10 dígitos (DDD + 8 dígitos).
    - Mantém números de 8, 9 (fixos ou celulares antigos) ou 11 dígitos como estão.
    
    Exemplos:
    - "+55 (11) 98765-4321" -> "11987654321" (11 dígitos, correto)
    - "551187654321"       -> "11987654321" (10 dígitos, adiciona o 9)
    - "1123456789"         -> "1123456789"  (10 dígitos, fixo, adiciona o 9 - Pipedrive pode lidar com isso)
    - "1140044004"         -> "1140044004"  (8 dígitos, fixo, mantém)
    - "656656856"          -> "656656856"   (9 dígitos, mantém)
    - "55656656856" (inválido no BR) -> "656656856" (9 dígitos, mantém)
    """
    if not isinstance(raw_phone, str):
        return ""
        
    # 1. Manter apenas os dígitos
    digits = re.sub(r"\D", "", raw_phone)

    # 2. Remover o código de país "55" no início
    if digits.startswith("55"):
        digits = digits[2:]

    # 3. Adicionar o nono dígito '9' se for um celular com 10 dígitos
    #    (DDD com 2 dígitos + número com 8 dígitos)
    if len(digits) == 10:
        ddd = digits[:2]
        # Adiciona o '9' após o DDD.
        return ddd + "9" + digits[2:]
        
    # 4. Retorna os dígitos limpos para outros casos (já com 11, ou fixos com 8/9)
    return digits

def _format_deal_details(data: Dict[str, Any]) -> Dict[str, Any]:
    """Formata a resposta detalhada de um deal em um dicionário limpo e útil."""
    if not data: 
        return {}
    valor_acordo_key = CUSTOM_FIELD_KEYS.get("valor_do_acordo")
    deal_value = data.get(valor_acordo_key) or data.get("value")
    custom_fields = {k: v for k, v in data.items() if re.match(r'^[0-9a-f]{40}$', k)}
    
    return {
        "id": data.get("id"), "title": data.get("title"), "value": deal_value,
        "formatted_value": data.get("formatted_value"), "currency": data.get("currency"),
        "status": data.get("status"),
        "user_id": data.get("user_id", {}).get("value"),
        "person_id": data.get("person_id", {}).get("value"),
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

async def find_deals_by_person_id(client: PipedriveClient, person_id: int) -> Optional[Dict[str, Any]]:
    """
    Busca os deals associados a uma pessoa pelo seu ID e retorna o mais relevante.
    A relevância é definida como o deal aberto atualizado mais recentemente.
    """
    logger.debug(f"Buscando deals para a pessoa ID: {person_id}")
    if not person_id:
        return None
        
    data = await client._request("GET", f"/persons/{person_id}/deals")
    
    if not data:
        return None
        
    # Filtra por deals que estão "abertos" e os ordena pela data de atualização
    open_deals = [d for d in data if d.get("status") == "open"]
    if not open_deals:
        return None
    # Ordena os deals abertos pela data de atualização, do mais recente para o mais antigo
    sorted_deals = sorted(open_deals, key=lambda d: d.get('update_time', ''), reverse=True)
    
    # Pega o ID do deal mais relevante e busca seus detalhes completos
    most_relevant_deal_id = sorted_deals[0].get("id")
    if most_relevant_deal_id:
        return await find_deal_by_id(client, most_relevant_deal_id)
        
    return None

async def find_person_by_phone(client: PipedriveClient, phone: str) -> Optional[Dict[str, Any]]:
    """
    Busca uma pessoa pelo telefone usando uma estratégia de busca em cascata para
    maximizar a chance de encontrar contatos com números não padronizados.
    """
    cleaned_phone_11_digits = _clean_phone(phone)
    if not cleaned_phone_11_digits:
        return None

    logger.debug(f"Iniciando busca em cascata para o telefone: {phone} (limpo: {cleaned_phone_11_digits})")

    # --- GERAÇÃO DE TERMOS APRIMORADA ---
    search_terms = set() # Usar um set para evitar duplicatas

    # 1. Adiciona o número com 11 dígitos (formato ideal)
    search_terms.add(cleaned_phone_11_digits)
    search_terms.update(_generate_phone_variations(cleaned_phone_11_digits))

    # 2. Se o número limpo tem 11 dígitos e o 3º é '9', cria versões com 10 dígitos
    if len(cleaned_phone_11_digits) == 11 and cleaned_phone_11_digits[2] == '9':
        cleaned_phone_10_digits = cleaned_phone_11_digits[:2] + cleaned_phone_11_digits[3:]
        search_terms.add(cleaned_phone_10_digits)
        search_terms.update(_generate_phone_variations(cleaned_phone_10_digits))

    search_terms_list = list(search_terms)
    logger.debug(f"Termos de busca gerados: {search_terms_list}")

    # --- INÍCIO DA BUSCA EM CASCATA ---
    
    # Tentativa 1: Busca exata com todos os termos gerados
    logger.debug(f"Tentando busca exata com os termos: {search_terms_list}")
    params_exact = {"fields": "phone,custom_fields", "exact_match": True}
    for term in search_terms_list:
        params_exact["term"] = term
        data = await client._request("GET", "/persons/search", params=params_exact)
        items = data.get("items", []) if data else []
        if items:
            person_id = items[0].get("item", {}).get("id")
            if person_id:
                logger.info(f"Pessoa encontrada com busca exata (termo: '{term}'). ID: {person_id}")
                return await find_person_by_id(client, person_id)

    # Tentativa 2: Busca flexível (sem exact_match) com todos os termos
    logger.debug(f"Busca exata falhou. Tentando busca flexível com os termos: {search_terms_list}")
    params_flexible = {"fields": "phone,custom_fields", "search_for_related_items": 1}
    for term in search_terms_list:
        params_flexible["term"] = term
        data = await client._request("GET", "/persons/search", params=params_flexible)
        items = data.get("items", []) if data else []
        if items:
            best_match = max(items, key=lambda x: x.get('result_score', 0))
            person_id = best_match.get("item", {}).get("id")
            if person_id:
                logger.info(f"Pessoa encontrada com busca flexível (termo: '{term}'). ID: {person_id}")
                return await find_person_by_id(client, person_id)

    logger.warning(f"Nenhuma pessoa encontrada para o telefone {phone} após todas as tentativas.")
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
    user_id: Optional[int] = None,
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
        
    if user_id:
        payload["user_id"] = user_id

    return await client._request("POST", "/activities", json=payload)

async def create_note_for_deal(
    client: PipedriveClient, 
    deal_id: int, 
    content: str
) -> Optional[Dict[str, Any]]:
    """
    Cria uma nova Nota e a associa a um Deal específico.

    Args:
        client: A instância do PipedriveClient a ser usada.
        deal_id: O ID do Deal ao qual a nota será anexada.
        content: O conteúdo da nota (em texto ou HTML).
    
    Returns:
        O dicionário de dados da nota criada ou None em caso de falha.
    """
    if not deal_id or not content:
        logger.error("Deal ID e conteúdo são obrigatórios para criar uma nota.")
        return None
        
    logger.info(f"Criando nota para o Deal ID {deal_id}...")
    
    payload = {
        "content": content,
        "deal_id": deal_id,
    }
    
    return await client._request("POST", "/notes", json=payload)