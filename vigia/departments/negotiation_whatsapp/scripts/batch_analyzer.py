import argparse
import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from db import models
from db.session import SessionLocal
from vigia.departments.negotiation_whatsapp.core.orchestrator import (
    run_department_pipeline,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


async def main_async():
    parser = argparse.ArgumentParser(
        description="Analisa um lote de conversas do banco de dados."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Número de conversas a serem analisadas (padrão: 5).",
    )
    parser.add_argument(
        "--strategy",
        choices=["longest", "latest"],
        default="longest",
        help="Estratégia: 'longest' (mais mensagens) ou 'latest' (mais recentes).",
    )
    parser.add_argument(
        "--instance",
        type=str,
        default=None,
        help="Filtra por instance_name. Aceita múltiplas separadas por vírgula (ex: 'GiovannaCelular,Joice').",
    )
    parser.add_argument(
        "--min-age-days",
        type=int,
        default=None,
        help="Seleciona conversas **mais antigas** com last_message_timestamp <= agora - N dias (ex: 45).",
    )
    args = parser.parse_args()

    logging.info(
        f"Iniciando análise em lote de {args.limit} conversas | strategy={args.strategy} | "
        f"instance={args.instance} | min_age_days={args.min_age_days}"
    )
    db: Session = SessionLocal()

    try:
        # Base query
        if args.strategy == "longest":
            q = (
                db.query(
                    models.WhatsappConversation.instance_name,
                    models.WhatsappConversation.remote_jid,
                    func.count(models.WhatsappMessage.id).label("message_count"),
                )
                .join(models.WhatsappMessage)
                .group_by(
                    models.WhatsappConversation.instance_name,
                    models.WhatsappConversation.remote_jid,
                )
                .order_by(func.count(models.WhatsappMessage.id).desc())
            )
        else:
            q = (
                db.query(
                    models.WhatsappConversation.instance_name,
                    models.WhatsappConversation.remote_jid,
                    func.max(models.WhatsappMessage.message_timestamp).label("last_ts"),
                )
                .join(models.WhatsappMessage)
                .group_by(
                    models.WhatsappConversation.instance_name,
                    models.WhatsappConversation.remote_jid,
                )
                .order_by(func.max(models.WhatsappMessage.message_timestamp).desc())
            )

        # Filtro por instância (se fornecido)
        if args.instance:
            instances = [s.strip() for s in args.instance.split(",") if s.strip()]
            q = q.filter(models.WhatsappConversation.instance_name.in_(instances))

        # Filtro por período mínimo (conversas antigas)
        if args.min_age_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=args.min_age_days)
            q = q.filter(models.WhatsappConversation.last_message_timestamp <= cutoff)

        query_result = q.limit(args.limit).all()
        if not query_result:
            logging.warning("Nenhuma conversa encontrada com os critérios fornecidos.")
            return

        conversations_to_analyze = [(row[0], row[1]) for row in query_result]
        logging.info("Conversas selecionadas: %s", conversations_to_analyze)

        tasks = []
        for instance_name, conv_jid in conversations_to_analyze:
            payload = {
                "conversation_id": conv_jid,
                "instance_name": instance_name,
            }
            tasks.append(run_department_pipeline(payload))

        logging.info("Disparando %d análises em paralelo...", len(tasks))
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            instance_name, conv_id = conversations_to_analyze[i]
            if isinstance(result, Exception):
                logging.error(
                    "[%s|%s] análise falhou: %s", instance_name, conv_id, result
                )
                tb_lines = traceback.format_exception(
                    type(result), result, result.__traceback__
                )
                logging.error("".join(tb_lines))
            elif result is None:
                logging.warning("[%s|%s] análise sem retorno.", instance_name, conv_id)
            else:
                logging.info(
                    "[%s|%s] análise concluída e salva.", instance_name, conv_id
                )

    except Exception as e:
        logging.error("Erro na análise em lote: %s", e, exc_info=True)
    finally:
        db.close()

    logging.info("Análise em lote concluída. ✅")


if __name__ == "__main__":
    asyncio.run(main_async())
