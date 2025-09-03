# vigia/utils/chatwoot.py
from __future__ import annotations
import re
from typing import Optional, Dict, Any

def _pick_last_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    msgs = payload.get("messages") or []
    if not isinstance(msgs, list) or not msgs:
        return None
    # created_at pode ser int (epoch) ou string; se não houver, cai para 0
    return max(msgs, key=lambda m: m.get("created_at") or m.get("updated_at") or 0)

def normalize_chatwoot_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Retorna um dicionário normalizado para o orquestrador:
    {
      'event', 'account_id', 'conversation_id', 'command', 'phone_number',
      'last_message', 'is_agent_message'
    }
    """
    event = payload.get("event")  # 'macro.executed' | 'message_created' | ...
    last_msg = _pick_last_message(payload) or {}

    account_id = (
        (payload.get("account") or {}).get("id")
        or payload.get("account_id")
        or last_msg.get("account_id")
    )

    conversation_id = (
        (payload.get("conversation") or {}).get("id")
        or payload.get("id")   # em macro.executed pode vir no root
        or last_msg.get("conversation_id")
    )

    # conteúdo / comando
    root_content = (payload.get("content") or "").strip()
    msg_content  = (last_msg.get("content") or "").strip()
    content = root_content or msg_content

    command = None
    if content.startswith("/"):
        command = content.split()[0].lower()
    elif event == "macro.executed":
        # trate macro como '/resumo' (ajuste aqui se tiver outras macros)
        command = "/resumo"

    # telefone (contact)
    sender = (payload.get("meta") or {}).get("sender") or (last_msg.get("sender") or {})
    phone_raw = sender.get("phone_number") or sender.get("identifier") or ""
    phone = re.sub(r"\D", "", phone_raw)

    is_agent_msg = last_msg.get("sender_type") in {"User", "agent", "Agent"}

    return {
        "event": event,
        "account_id": account_id,
        "conversation_id": conversation_id,
        "command": command,
        "phone_number": phone,
        "last_message": last_msg,
        "is_agent_message": is_agent_msg
    }
