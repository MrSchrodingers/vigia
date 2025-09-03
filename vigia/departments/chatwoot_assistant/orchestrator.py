# vigia/departments/chatwoot_assistant/orchestrator.py
from __future__ import annotations
import logging
import re
from typing import Any, Dict, Optional, Tuple
from . import commands
from . import chatwoot_api
from db.session import SessionLocal
from vigia.departments.negotiation_whatsapp.core.orchestrator import (
    fetch_history_and_date_from_db,
    run_context_department,
)

logger = logging.getLogger(__name__)

COMMAND_MAPPING = {
    "/resumo": commands.get_summary,
    "/pipedrive": commands.get_pipedrive_info,
    "/acao": commands.get_recommended_action,
}

def _pick_last_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    msgs = payload.get("messages") or []
    if not isinstance(msgs, list) or not msgs: 
        return None
    return max(msgs, key=lambda m: m.get("created_at") or m.get("updated_at") or 0)

def _extract_ids(payload: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    norm = payload.get("_norm") or {}
    account_id = (
        norm.get("account_id")
        or (payload.get("account") or {}).get("id")
        or payload.get("account_id")
        or ((_pick_last_message(payload) or {}).get("account_id"))
    )
    conversation_id = (
        norm.get("conversation_id")
        or (payload.get("conversation") or {}).get("id")
        or payload.get("id")
        or ((_pick_last_message(payload) or {}).get("conversation_id"))
    )
    try: 
        account_id = int(account_id) if account_id is not None else None
    except (ValueError, TypeError): 
        account_id = None
    try: 
        conversation_id = int(conversation_id) if conversation_id is not None else None
    except (ValueError, TypeError): 
        conversation_id = None
    return account_id, conversation_id

def _extract_command(payload: Dict[str, Any]) -> Optional[str]:
    norm = payload.get("_norm") or {}
    if isinstance(norm.get("command"), str): 
        return norm["command"].strip().lower()
    if isinstance(payload.get("command"), str): 
        return payload["command"].strip().lower()
    root_content = (payload.get("content") or "").strip()
    if root_content.startswith("/"): 
        return root_content.split()[0].lower()
    last_msg = _pick_last_message(payload) or {}
    msg_content = (last_msg.get("content") or "").strip()
    if msg_content.startswith("/"): 
        return msg_content.split()[0].lower()
    return None

def _digits_only(v: Optional[str]) -> str:
    return re.sub(r"\D", "", v or "")

def _extract_phone_number(payload: Dict[str, Any]) -> str:
    norm = payload.get("_norm") or {}
    if norm.get("phone_number"): 
        return _digits_only(norm["phone_number"])
    sender = (payload.get("meta") or {}).get("sender") or {}
    phone = sender.get("phone_number") or sender.get("identifier")
    if phone: 
        return _digits_only(phone)
    last_msg = _pick_last_message(payload) or {}
    l_sender = last_msg.get("sender") or {}
    phone = l_sender.get("phone_number") or l_sender.get("identifier")
    if phone: 
        return _digits_only(phone)
    phone = (payload.get("contact") or {}).get("phone_number")  # legado
    return _digits_only(phone)

async def _send_note(account_id: int, conversation_id: int, content: str) -> None:
    try:
        await chatwoot_api.send_private_message(account_id, conversation_id, content)
    except Exception:
        logger.exception("Falha ao enviar nota privada para %s/%s", account_id, conversation_id)

async def handle_task(payload: dict):
    """
    Fluxo:
      1) Extrai account_id, conversation_id, command e phone do payload.
      2) Busca histórico no DB (com transcrições via pipeline do WhatsApp).
      3) Busca contexto (Pipedrive).
      4) Executa o comando (/resumo, /pipedrive, /acao).
      5) Envia resposta como NOTA PRIVADA.
    """
    account_id, conversation_id = _extract_ids(payload)
    if not account_id or not conversation_id:
        logger.warning("Sem account_id/conversation_id resolvido; keys=%s", list(payload.keys()))
        return

    command = _extract_command(payload)
    if not command:
        await _send_note(account_id, conversation_id,
                         "Comando ausente. Use: /resumo, /pipedrive, /acao.")
        return

    fn = COMMAND_MAPPING.get(command)
    if not fn:
        await _send_note(account_id, conversation_id,
                         f"Comando '{command}' não reconhecido. Disponíveis: /resumo, /pipedrive, /acao.")
        return

    phone_number = _extract_phone_number(payload)
    if not phone_number:
        logger.warning("Telefone do contato não encontrado no payload.")
        await _send_note(account_id, conversation_id,
                         "Erro: não foi possível identificar o número do contato.")
        return

    conversation_jid = f"{phone_number}@s.whatsapp.net"

    await _send_note(account_id, conversation_id,
                     f"Recebi '{command}'. Buscando histórico e contexto… 🤖")

    db = SessionLocal()
    try:
        history, last_date = fetch_history_and_date_from_db(db, conversation_jid)
        if not history:
            msg = (f"Não encontrei histórico de conversa para {phone_number} no banco VigIA. "
                   f"Verifique a sincronização da origem.")
            logger.warning(msg)
            await _send_note(account_id, conversation_id, msg)
            return

        context = await run_context_department(conversation_jid)
    finally:
        db.close()

    try:
        if command == "/resumo":
            result = await fn(history, context, last_date)
        elif command == "/pipedrive":
            result = await fn(context)
        elif command == "/acao":
            result = await fn(history, context, conversation_jid)
        else:
            result = "Comando válido, porém sem implementação ativa no orquestrador."

        await _send_note(account_id, conversation_id, result)

    except Exception as e:
        logger.error("Erro ao executar '%s' para %s: %s",
                     command, conversation_jid, e, exc_info=True)
        await _send_note(account_id, conversation_id,
                         f"Ocorreu um erro ao processar '{command}'. A equipe técnica foi notificada.")
