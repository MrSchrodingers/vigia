from __future__ import annotations
import httpx
import os
import logging

CHATWOOT_API_URL = os.getenv("CHATWOOT_API_URL") 
CHATWOOT_API_TOKEN = os.getenv("CHATWOOT_BOT_TOKEN")

async def send_private_message(account_id: int, conversation_id: int, content: str):
    """
    Envia nota privada (apenas agentes) na conversa do Chatwoot.
    Usa endpoint: POST /api/v1/accounts/{account_id}/conversations/{conversation_id}/messages
    """
    if not CHATWOOT_API_URL or not CHATWOOT_API_TOKEN:
        logging.error("CHATWOOT_API_URL / CHATWOOT_BOT_TOKEN ausentes.")
        return

    base = CHATWOOT_API_URL.rstrip("/")
    url = f"{base}/api/v1/accounts/{account_id}/conversations/{conversation_id}/messages"
    headers = {"api_access_token": CHATWOOT_API_TOKEN, "Content-Type": "application/json"}

    payload = {
        "content": f"🤖 **VigIA** — resumo\n\n{content}",
        "private": True,                # nota interna
        "message_type": "outgoing",     # emitido como bot/agent
        "content_type": "text",
        "content_attributes": {"source": "vigia", "kind": "summary"}
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            logging.info("Nota privada postada em %s/%s", account_id, conversation_id)
        except httpx.HTTPStatusError as e:
            logging.error("Chatwoot %s: %s", e.response.status_code, e.response.text)
        except Exception as e:
            logging.error("Falha ao postar nota privada: %s", e, exc_info=True)
