import logging
import requests
from collections import defaultdict
from db.session import SessionLocal
from vigia.config import settings
from vigia.services.database_service import save_raw_conversation
from vigia.departments.negotiation_whatsapp.scripts.decrypt_whatsapp_media import (
    decrypt_whatsapp_media,
)
from vigia.departments.negotiation_whatsapp.scripts.transcribe_audio_with_whisper import (
    transcribe_audio_with_whisper,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
RECORDS_PER_PAGE = 50

SKIP_TYPES = {
    "videoMessage":     "[VIDEO ENVIADO]",
    "documentMessage":  "[DOCUMENTO ENVIADO]",
    "imageMessage":     "[IMAGEM ENVIADA]",
    "stickerMessage":   "[STICKER ENVIADO]",
}


def _fetch_page(page: int) -> dict:
    """Chama a Evolution API e devolve o JSON bruto da página solicitada."""
    resp = requests.post(
        f"{settings.EVOLUTION_BASE_URL}/chat/findMessages/{settings.INSTANCE_NAME}",
        headers={"apikey": settings.API_KEY},
        json={"page": page, "size": RECORDS_PER_PAGE, "sort": "desc"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _handle_audio(msg: dict) -> str:
    """Baixa, decifra e transcreve uma nota de voz."""
    audio = msg["message"]["audioMessage"]
    enc   = requests.get(audio["url"], timeout=30).content
    plain = decrypt_whatsapp_media(enc, audio["mediaKey"])
    text  = transcribe_audio_with_whisper(plain) or "TRANSC. FALHOU"
    return f"[ÁUDIO]: {text}"


def main() -> None:
    logging.info("Iniciando INGESTÃO de histórico da Evolution API.")
    page, total_pages = 1, 1
    db = SessionLocal()

    try:
        while page <= total_pages:
            logging.info("Buscando página %s/%s…", page, total_pages)
            data    = _fetch_page(page)
            records = data.get("messages", {}).get("records", [])
            if not records:
                break

            grouped = defaultdict(list)

            for msg in records:
                conv_id = msg["key"].get("remoteJid")
                ext_id  = msg["key"].get("id")
                if not conv_id or not ext_id:
                    continue

                msg_type   = msg.get("messageType")
                sender     = "Negociador" if msg["key"].get("fromMe") else "Cliente"
                timestamp  = msg.get("messageTimestamp", 0)

                # ─── 1. TEXTOS ────────────────────────────────────────────
                if msg_type == "conversation":
                    text = msg["message"]["conversation"].strip()

                # ─── 2. ÁUDIOS ────────────────────────────────────────────
                elif msg_type == "audioMessage":
                    try:
                        text = _handle_audio(msg)
                    except Exception as e:
                        logging.error("Falha no áudio %s: %s", ext_id, e)
                        text = "[FALHA ÁUDIO]"

                # ─── 3. OUTRAS MÍDIAS (placeholder) ─────────────────────
                elif msg_type in SKIP_TYPES:
                    text = SKIP_TYPES[msg_type]

                # ─── 4. QUALQUER OUTRO TIPO ─────────────────────────────
                else:
                    text = f"[{msg_type.upper()}]"

                if text.startswith("*") and ":*" in text:
                    text = text.split(":*", 1)[-1].strip()

                grouped[conv_id].append(
                    dict(sender=sender, text=text,
                         timestamp=timestamp, external_id=ext_id)
                )

            for conv_id, msgs in grouped.items():
                save_raw_conversation(db, conversation_jid=conv_id, messages=msgs)

            page += 1
            total_pages = data.get("messages", {}).get("pages", 1)

    except Exception:
        logging.exception("Erro durante ingestão")
    finally:
        db.close()
        logging.info("Ingestão finalizada.")


if __name__ == "__main__":
    main()
