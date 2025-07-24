import logging
import re
from typing import Optional
import httpx
from ..config import settings
from datetime import datetime

BASE_URL = settings.PIPEDRIVE_DOMAIN
API_TOKEN = settings.PIPEDRIVE_API_TOKEN

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
  
async def find_person_by_phone(phone: str) -> dict | None:
    """Encontra uma pessoa no Pipedrive pelo telefone e retorna seu ID e nome."""
    if not API_TOKEN:
        logging.warning("PIPEDRIVE_API_TOKEN não configurado.")
        return None

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{BASE_URL}/persons/search",
                params={"term": clean_phone(phone), "fields": "custom_fields,phone", "api_token": API_TOKEN}
            )
            response.raise_for_status()
            data = response.json()
            if data.get("data", {}).get("items"):
                person_item = data["data"]["items"][0]["item"]
                person_info = {
                    "id": person_item.get("id"),
                    "name": person_item.get("name")
                }
                logging.info(f"Pessoa encontrada no Pipedrive: {person_info} para o telefone {phone}.")
                return person_info 
        except httpx.RequestError as e:
            logging.error(f"Erro ao buscar pessoa no Pipedrive: {e}")
        return None

async def find_deal_by_person_name(person_name: str) -> dict | None:
    """Encontra um deal no Pipedrive pelo nome da pessoa associada."""
    if not API_TOKEN:
        logging.warning("PIPEDRIVE_API_TOKEN não configurado.")
        return None

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{BASE_URL}/deals/search",
                params={"term": person_name, "fields": "title", "exact_match": False, "api_token": API_TOKEN}
            )
            response.raise_for_status()
            data = response.json()
            if data.get("data", {}).get("items"):
                deal_item = data["data"]["items"][0]["item"]
                logging.info(f"Deal encontrado com ID {deal_item.get('id')} para a pessoa {person_name}.")
                return deal_item 
        except httpx.RequestError as e:
            logging.error(f"Erro ao buscar deal no Pipedrive: {e}")
        return None
      
async def create_activity(
    person_id: int,
    due_date: str,
    note_summary: str,
    deal_id: Optional[int] = None,
    subject: str = "Follow-up de Cobrança"
) -> dict:
    """Cria uma nova atividade (tarefa) no Pipedrive."""
    if not API_TOKEN:
        return {"error": "Pipedrive API token não configurado."}

    # Valida e formata a data
    try:
        valid_date = datetime.fromisoformat(due_date).strftime('%Y-%m-%d')
    except ValueError:
        logging.error(f"Formato de data inválido para a atividade do Pipedrive: {due_date}")
        return {"error": f"Data inválida: {due_date}. Use o formato AAAA-MM-DD."}

    payload = {
        "subject": subject,
        "type": "task",          # ou 'call', 'meeting', etc.
        "due_date": valid_date,
        "person_id": person_id,
        "note": note_summary,
    }
    if deal_id:                  # só envia se houver negócio associado
        payload["deal_id"] = deal_id

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BASE_URL}/activities",
                params={"api_token": API_TOKEN},
                json=payload
            )
            response.raise_for_status()
            result = response.json().get("data", {})
            logging.info(f"Atividade criada com sucesso no Pipedrive com ID {result.get('id')}.")
            return result
        except httpx.RequestError as e:
            logging.error(f"Erro ao criar atividade no Pipedrive: {e}")
            return {"error": str(e)}