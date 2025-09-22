# -*- coding: utf-8 -*-
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

import requests

from db.session import SessionLocal
from vigia.config import settings
from vigia.departments.negotiation_whatsapp.scripts.crash_guard import (
    install_crash_guard,
)
from vigia.departments.negotiation_whatsapp.scripts.decrypt_whatsapp_media import (
    decrypt_whatsapp_media,
)
from vigia.departments.negotiation_whatsapp.scripts.resource_monitor import (
    start_resource_monitor,
)
from vigia.departments.negotiation_whatsapp.scripts.transcribe_audio_with_whisper import (
    transcribe_audio_with_whisper,
)
from vigia.services.database_service import save_raw_conversation

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

RECORDS_PER_PAGE = 50
MAX_FETCH_RETRIES = 5
BACKOFF_BASE_SECONDS = 2.0

SKIP_TYPES = {
    "videoMessage": "[VIDEO ENVIADO]",
    "documentMessage": "[DOCUMENTO ENVIADO]",
    "imageMessage": "[IMAGEM ENVIADA]",
    "stickerMessage": "[STICKER ENVIADO]",
}

LOW_CONF_THRESHOLD = 0.60


def _download_media(url: str, min_size: int = 128) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or len(r.content) < min_size:
            logger.debug(
                "Download media falhou/pequeno (status=%s, len=%s)",
                r.status_code,
                len(r.content),
            )
            return None
        return r.content
    except requests.RequestException as exc:
        logger.debug("Download media exception: %s", exc)
        return None


def _fetch_page(instance_name: str, page: int) -> Dict[str, Any]:
    url = f"{settings.EVOLUTION_BASE_URL}/chat/findMessages/{instance_name}"
    payload = {"page": page, "size": RECORDS_PER_PAGE, "sort": "desc"}
    headers = {"apikey": settings.API_KEY}

    for attempt in range(1, MAX_FETCH_RETRIES + 1):
        try:
            logger.debug("[%s] POST %s payload=%s", instance_name, url, payload)
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
                    "[%s] Falha permanente ao buscar página %s (%s tentativas): %s",
                    instance_name,
                    page,
                    attempt,
                    exc,
                )
                raise
            backoff = BACKOFF_BASE_SECONDS**attempt
            logger.warning(
                "[%s] Tentativa %s/%s para page %s falhou (%s). Retry em %.1f s…",
                instance_name,
                attempt,
                MAX_FETCH_RETRIES,
                page,
                exc,
                backoff,
            )
            time.sleep(backoff)


def _extract_total_pages(data: Dict[str, Any]) -> int:
    """
    Evolutions diferentes expõem total de páginas como:
      data['messages']['pages'] OU ['messages']['totalPages'] OU ['pages'] OU ['totalPages'].
    """
    msg = data.get("messages") or {}
    candidates = [
        msg.get("pages"),
        msg.get("totalPages"),
        data.get("pages"),
        data.get("totalPages"),
    ]
    for c in candidates:
        try:
            if c is not None:
                return int(c)
        except (TypeError, ValueError):
            continue
    return 1


def _handle_audio(msg: dict) -> str:
    audio = msg["message"]["audioMessage"]
    raw = _download_media(audio["url"])
    if raw is None:
        return "[ÁUDIO EXPIRADO]"

    try:
        plain = decrypt_whatsapp_media(raw, audio["mediaKey"])
    except ValueError:
        return "[ÁUDIO CORROMPIDO]"

    # Chama o cliente (subprocesso) — blindado
    text = transcribe_audio_with_whisper(plain) or "TRANSC. FALHOU"

    # Realce de baixa confiança (mantém sua regra)
    if "CONFIDÊNCIA=" in text:
        try:
            conf = float(text.split("CONFIDÊNCIA=")[1].split("]")[0])
            if conf < LOW_CONF_THRESHOLD:
                text = text.replace("]:", " BAIXA]:")
        except Exception:
            pass
    return text


def run_import_for_instance(instance_name: str) -> None:
    logger.info("[%s] Iniciando INGESTÃO de histórico.", instance_name)
    page = 1
    total_pages = 1  # valor provisório até a 1ª resposta
    db = SessionLocal()

    total_records = 0
    total_inserted_msgs = 0
    start_t0 = time.perf_counter()

    try:
        while page <= total_pages:
            t_page0 = time.perf_counter()
            logger.info("[%s] Buscando página %s/%s…", instance_name, page, total_pages)

            data = _fetch_page(instance_name, page)
            # após 1ª resposta, corrija total_pages e logue explicitamente
            real_total = _extract_total_pages(data)
            if total_pages != real_total:
                total_pages = real_total
                if page == 1:
                    logger.info(
                        "[%s] Total de páginas detectado: %s",
                        instance_name,
                        total_pages,
                    )

            records = (data.get("messages") or {}).get("records", []) or []
            rec_count = len(records)
            total_records += rec_count
            logger.info(
                "[%s] Página %s/%s: %s registros",
                instance_name,
                page,
                total_pages,
                rec_count,
            )

            if not records:
                logger.warning(
                    "[%s] Página %s veio vazia; encerrando.", instance_name, page
                )
                break

            grouped: dict[str, list[dict]] = defaultdict(list)
            seen: dict[str, set[str]] = defaultdict(set)

            for msg in records:
                conv_id = (msg.get("key") or {}).get("remoteJid")
                ext_id = (msg.get("key") or {}).get("id")
                if not conv_id or not ext_id or ext_id in seen[conv_id]:
                    continue
                seen[conv_id].add(ext_id)

                msg_type = msg.get("messageType")
                sender = (
                    "Negociador" if (msg.get("key") or {}).get("fromMe") else "Cliente"
                )
                timestamp = msg.get("messageTimestamp", 0)

                if msg_type == "conversation":
                    text = (msg.get("message") or {}).get("conversation", "").strip()
                elif msg_type == "audioMessage":
                    try:
                        text = _handle_audio(msg)
                    except Exception as e:
                        logger.error(
                            "[%s] Falha no áudio %s: %s", instance_name, ext_id, e
                        )
                        text = "[FALHA ÁUDIO]"
                elif msg_type in SKIP_TYPES:
                    text = SKIP_TYPES[msg_type]
                else:
                    text = f"[{msg_type.upper()}]"

                if text.startswith("*") and ":*" in text:
                    text = text.split(":*", 1)[-1].strip()

                grouped[conv_id].append(
                    {
                        "sender": sender,
                        "text": text,
                        "timestamp": timestamp,
                        "external_id": ext_id,
                        "message_type": msg_type,
                    }
                )

            unique_msgs = sum(len(v) for v in grouped.values())
            logger.info(
                "[%s] Página %s/%s: %s conversas agrupadas; %s mensagens únicas agregadas",
                instance_name,
                page,
                total_pages,
                len(grouped),
                unique_msgs,
            )

            inserted_this_page = 0
            for conv_id, msgs in grouped.items():
                inc = save_raw_conversation(
                    db,
                    instance_name=instance_name,
                    conversation_jid=conv_id,
                    messages=msgs,
                )
                inserted_this_page += inc

            total_inserted_msgs += inserted_this_page
            t_page1 = time.perf_counter()
            logger.info(
                "[%s] Página %s/%s concluída em %.2fs | novos inserts=%s",
                instance_name,
                page,
                total_pages,
                (t_page1 - t_page0),
                inserted_this_page,
            )

            page += 1

    except Exception:
        logger.exception("[%s] Erro durante ingestão", instance_name)
    finally:
        db.close()
        dt_total = time.perf_counter() - start_t0
        logger.info(
            "[%s] Ingestão finalizada. páginas=%s registros=%s novos_inserts=%s tempo_total=%.2fs",
            instance_name,
            (page - 1),
            total_records,
            total_inserted_msgs,
            dt_total,
        )


def main() -> None:
    # Estes envs aqui ajudam outras libs, mas o worker já seta os dele internamente.
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    start_resource_monitor(interval_sec=15.0)
    install_crash_guard()

    instances = settings.INSTANCE_NAMES
    if not instances:
        logger.warning("INSTANCE_NAME vazio; nada a fazer.")
        return

    max_workers = min(len(instances), settings.WPP_IMPORT_MAX_INSTANCE_WORKERS or 1)
    logger.info(
        "Rodando import para %d instâncias (max_workers=%d): %s",
        len(instances),
        max_workers,
        instances,
    )

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(run_import_for_instance, name): name for name in instances}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                fut.result()
            except Exception as e:
                logger.error("[%s] Importer encerrou com erro: %s", name, e)


if __name__ == "__main__":
    import os

    main()
