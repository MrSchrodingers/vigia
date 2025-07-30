import logging
import time
from collections import defaultdict
from typing import Any, Dict, Optional

import requests
from db.session import SessionLocal
from vigia.config import settings
from vigia.services.database_service import save_raw_conversation
from vigia.departments.negotiation_whatsapp.scripts.decrypt_whatsapp_media import (
    decrypt_whatsapp_media,
)
from vigia.departments.negotiation_whatsapp.scripts.transcribe_audio_with_whisper import (
    transcribe_audio_with_whisper,
)

# ─────────────────────────  Configuração de log  ──────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────  Constantes  ───────────────────────────────────
RECORDS_PER_PAGE     = 50
MAX_FETCH_RETRIES    = 5          # tentativas
BACKOFF_BASE_SECONDS = 2.0        # 1ª espera = 2 s, depois 4 s, 8 s…

SKIP_TYPES = {
    "videoMessage":    "[VIDEO ENVIADO]",
    "documentMessage": "[DOCUMENTO ENVIADO]",
    "imageMessage":    "[IMAGEM ENVIADA]",
    "stickerMessage":  "[STICKER ENVIADO]",
}

LOW_CONF_THRESHOLD = 0.60


# ─────────────────────────  Funções utilitárias  ──────────────────────────
def _download_media(url: str, min_size: int = 128) -> Optional[bytes]:
    """Baixa mídia do WhatsApp; devolve None se link expirado/incompleto."""
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or len(r.content) < min_size:
            return None
        return r.content
    except requests.RequestException:
        return None


def _fetch_page(page: int) -> Dict[str, Any]:
    """
    Chama a Evolution API com RETRY exponencial.
    - Tenta até MAX_FETCH_RETRIES vezes.
    - Faz back‑off 2, 4, 8, 16 … segundos.
    - Relança o erro se todas as tentativas falharem.
    """
    url = f"{settings.EVOLUTION_BASE_URL}/chat/findMessages/{settings.INSTANCE_NAME}"
    payload = {"page": page, "size": RECORDS_PER_PAGE, "sort": "desc"}
    headers = {"apikey": settings.API_KEY}

    for attempt in range(1, MAX_FETCH_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            if resp.status_code >= 500:
                raise requests.HTTPError(
                    f"{resp.status_code} {resp.reason}", response=resp
                )
            resp.raise_for_status()
            return resp.json()

        except requests.RequestException as exc:
            if attempt == MAX_FETCH_RETRIES:
                logger.error(
                    "Falha permanente ao buscar página %s (%s tentativas): %s",
                    page,
                    attempt,
                    exc,
                )
                raise                     # deixa o importador encerrar com traceback
            backoff = BACKOFF_BASE_SECONDS ** attempt
            logger.warning(
                "Tentativa %s/%s para page %s falhou (%s). "
                "Retry em %.1f s…",
                attempt,
                MAX_FETCH_RETRIES,
                page,
                exc,
                backoff,
            )
            time.sleep(backoff)


def _handle_audio(msg: dict) -> str:
    """Resolve download, descriptografia e transcrição de áudio."""
    audio = msg["message"]["audioMessage"]
    raw = _download_media(audio["url"])
    if raw is None:
        return "[ÁUDIO EXPIRADO]"

    try:
        plain = decrypt_whatsapp_media(raw, audio["mediaKey"])
    except ValueError:
        return "[ÁUDIO CORROMPIDO]"

    text = transcribe_audio_with_whisper(plain) or "TRANSC. FALHOU"
    if "CONFIDÊNCIA=" in text:
        conf = float(text.split("CONFIDÊNCIA=")[1].split("]")[0])
        if conf < LOW_CONF_THRESHOLD:
            text = text.replace("]:", " BAIXA]:")
    return text


# ─────────────────────────  Loop principal  ───────────────────────────────
def main() -> None:
    logger.info("Iniciando INGESTÃO de histórico da Evolution API.")
    page, total_pages = 1, 1
    db = SessionLocal()

    try:
        while page <= total_pages:
            logger.info("Buscando página %s/%s…", page, total_pages)
            data = _fetch_page(page)
            records = data.get("messages", {}).get("records", [])
            if not records:
                break

            grouped: dict[str, list[dict]] = defaultdict(list)
            seen: dict[str, set[str]] = defaultdict(set)

            for msg in records:
                conv_id = msg["key"].get("remoteJid")
                ext_id = msg["key"].get("id")
                if not conv_id or not ext_id or ext_id in seen[conv_id]:
                    continue
                seen[conv_id].add(ext_id)

                msg_type = msg.get("messageType")
                sender = "Negociador" if msg["key"].get("fromMe") else "Cliente"
                timestamp = msg.get("messageTimestamp", 0)

                # 1. Texto
                if msg_type == "conversation":
                    text = msg["message"]["conversation"].strip()

                # 2. Áudio
                elif msg_type == "audioMessage":
                    try:
                        text = _handle_audio(msg)
                    except Exception as e:  # noqa BLE001
                        logger.error("Falha no áudio %s: %s", ext_id, e)
                        text = "[FALHA ÁUDIO]"

                # 3. Demais mídias
                elif msg_type in SKIP_TYPES:
                    text = SKIP_TYPES[msg_type]

                # 4. Qualquer outro
                else:
                    text = f"[{msg_type.upper()}]"

                # Remove formatação “*Fulano:*” típica de WhatsApp‑Web
                if text.startswith("*") and ":*" in text:
                    text = text.split(":*", 1)[-1].strip()

                grouped[conv_id].append(
                    {
                        "sender": sender,
                        "text": text,
                        "timestamp": timestamp,
                        "external_id": ext_id,
                    }
                )

            # Persistência idempotente
            for conv_id, msgs in grouped.items():
                save_raw_conversation(db, conversation_jid=conv_id, messages=msgs)

            page += 1
            total_pages = data.get("messages", {}).get("pages", 1)

    except Exception:
        logger.exception("Erro durante ingestão")
    finally:
        db.close()
        logger.info("Ingestão finalizada.")


if __name__ == "__main__":
    main()
