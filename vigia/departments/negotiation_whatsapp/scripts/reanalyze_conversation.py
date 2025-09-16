import argparse
import asyncio
import json
import logging
from datetime import datetime
from typing import Tuple

from sqlalchemy.orm import Session

from db import models
from db.session import SessionLocal
from vigia.departments.negotiation_whatsapp.core.orchestrator import (
    run_department_pipeline,
)
from vigia.services import database_service

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def fetch_history_and_date_from_db(
    db: Session, conversation_jid: str
) -> Tuple[str, datetime]:
    """Busca o histórico e a data da ÚLTIMA mensagem de uma conversa no banco."""
    logging.info(f"Buscando histórico do DB para: {conversation_jid}")
    messages = (
        db.query(models.WhatsappMessage)
        .join(models.WhatsappConversation)
        .filter(models.WhatsappConversation.remote_jid == conversation_jid)
        .order_by(models.WhatsappMessage.message_timestamp.asc())
        .all()
    )
    if not messages:
        return "", None

    history_text = "\n".join([f"{msg.sender}: {msg.text}" for msg in messages])
    last_message_date = messages[-1].message_timestamp
    return history_text, last_message_date


async def main_async():
    parser = argparse.ArgumentParser(
        description="Reanalisa uma conversa do WhatsApp do banco de dados."
    )
    parser.add_argument(
        "--conversa", required=True, help="O ID da conversa (remoteJid)"
    )
    parser.add_argument(
        "--salvar",
        action="store_true",
        help="Salva o resultado da análise no banco de dados.",
    )
    args = parser.parse_args()

    logging.info(f"Iniciando reanálise para a conversa: {args.conversa}")

    payload = {"conversation_id": args.conversa}

    try:
        final_report = await run_department_pipeline(payload)

        if not final_report:
            logging.warning(
                f"A reanálise para a conversa {args.conversa} não produziu um relatório. Verifique os logs do orquestrador."
            )
            return

        print("\n--- RELATÓRIO DE REANÁLISE COMPLETO ---")
        print(json.dumps(final_report, indent=2, ensure_ascii=False))
        print("-----------------------------------------\n")

        if args.salvar:
            logging.info(
                "Flag --salvar detectada. Salvando análise no banco de dados..."
            )
            db: Session = SessionLocal()
            try:
                database_service.save_whatsapp_analysis_results(
                    db=db, conversation_jid=args.conversa, analysis_data=final_report
                )
                logging.info("Análise salva com sucesso!")
            except Exception as e:
                logging.error(f"Erro ao salvar a análise no banco: {e}", exc_info=True)
            finally:
                db.close()

    except Exception as e:
        logging.error(
            f"Ocorreu um erro fatal durante a reanálise da conversa {args.conversa}: {e}",
            exc_info=True,
        )


if __name__ == "__main__":
    asyncio.run(main_async())
