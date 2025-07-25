import argparse
import logging
import asyncio
import traceback
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.session import SessionLocal
from db import models 
from vigia.departments.negotiation_email.core.orchestrator import run_department_pipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main_async():
    """
    Script para analisar um lote de threads de e-mail do banco de dados.
    """
    parser = argparse.ArgumentParser(description="Analisa um lote de threads de e-mail.")
    parser.add_argument("--limit", type=int, default=10, help="Número de threads a serem analisadas (padrão: 10).")
    parser.add_argument(
        "--strategy", 
        choices=['longest', 'latest'], 
        default='latest', 
        help="Estratégia: 'longest' (com mais e-mails) ou 'latest' (mais recentes)."
    )
    args = parser.parse_args()

    logging.info(f"Iniciando análise em lote de {args.limit} threads usando a estratégia '{args.strategy}'.")
    db: Session = SessionLocal()
    threads_to_analyze = []
    
    try:
        if args.strategy == 'longest':
            # Query para encontrar as threads com mais mensagens
            query_result = (
                db.query(models.EmailThread.conversation_id)
                .join(models.EmailMessage)
                .group_by(models.EmailThread.conversation_id)
                .order_by(func.count(models.EmailMessage.id).desc())
                .limit(args.limit)
                .all()
            )
        else:  # latest
            # Query para encontrar as threads com a última mensagem mais recente
            query_result = (
                db.query(models.EmailThread.conversation_id)
                .order_by(models.EmailThread.last_email_date.desc())
                .limit(args.limit)
                .all()
            )
        
        threads_to_analyze = [row[0] for row in query_result]

        if not threads_to_analyze:
            logging.warning("Nenhuma thread de e-mail encontrada para analisar.")
            return

        logging.info(f"Threads selecionadas para análise: {threads_to_analyze}")
        
        tasks = [run_department_pipeline({"conversation_id": thread_id, "save_result": True}) for thread_id in threads_to_analyze]
        
        logging.info(f"Disparando {len(tasks)} análises em paralelo...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            thread_id = threads_to_analyze[i]
            if isinstance(result, Exception):
                logging.error(f"A análise para a thread {thread_id} falhou com uma exceção: {result}")
                tb = "".join(traceback.format_exception(type(result), result, result.__traceback__))
                logging.error(tb)
            else:
                logging.info(f"Análise para a thread {thread_id} concluída com sucesso.")
                
    except Exception as e:
        logging.error(f"Ocorreu um erro crítico durante a análise em lote: {e}", exc_info=True)
    finally:
        db.close()
    
    logging.info("Análise em lote de e-mails concluída. ✅")

if __name__ == "__main__":
    asyncio.run(main_async())