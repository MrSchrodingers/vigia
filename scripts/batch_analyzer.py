import argparse
import logging
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy import func

from db.session import SessionLocal
from db import models
from vigia.core.orchestrator import run_multi_agent_cycle_async

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main_async():
    parser = argparse.ArgumentParser(description="Analisa um lote de conversas do banco de dados.")
    parser.add_argument(
        "--limit", 
        type=int, 
        default=5, 
        help="Número de conversas a serem analisadas (padrão: 5)."
    )
    parser.add_argument(
        "--strategy", 
        choices=['longest', 'latest'], 
        default='longest', 
        help="Estratégia para selecionar conversas: 'longest' (com mais mensagens) ou 'latest' (mais recentes)."
    )
    args = parser.parse_args()

    logging.info(f"Iniciando análise em lote de {args.limit} conversas usando a estratégia '{args.strategy}'.")
    db: Session = SessionLocal()
    conversations_to_analyze = []
    
    try:
        if args.strategy == 'longest':
            # Query para encontrar as conversas com mais mensagens
            query_result = (
                db.query(models.Conversation.remote_jid, func.count(models.Message.id).label('message_count'))
                .join(models.Message)
                .group_by(models.Conversation.remote_jid)
                .order_by(func.count(models.Message.id).desc())
                .limit(args.limit)
                .all()
            )
        else: # latest
            # Query para encontrar as conversas mais recentes
            query_result = (
                db.query(models.Conversation.remote_jid)
                .order_by(models.Conversation.created_at.desc())
                .limit(args.limit)
                .all()
            )
        
        conversations_to_analyze = [row[0] for row in query_result]

        if not conversations_to_analyze:
            logging.warning("Nenhuma conversa encontrada no banco para analisar com os critérios fornecidos.")
            return

        logging.info(f"Conversas selecionadas para análise: {conversations_to_analyze}")
        
        # Cria uma "tarefa" assíncrona para cada conversa
        tasks = []
        for conv_id in conversations_to_analyze:
            payload = {"conversation_id": conv_id}
            # Adicionamos a execução do orquestrador como uma tarefa na lista
            tasks.append(run_multi_agent_cycle_async(payload))
        
        # Executa todas as tarefas de análise em paralelo
        logging.info(f"Disparando {len(tasks)} análises em paralelo...")
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Itera sobre os resultados para confirmar o salvamento
        for i, result in enumerate(results):
            conv_id = conversations_to_analyze[i]
            if isinstance(result, Exception):
                logging.error(f"A análise para a conversa {conv_id} falhou com uma exceção: {result}")
            elif result is None:
                logging.warning(f"A análise para a conversa {conv_id} não retornou um resultado (verifique os logs do worker para erros).")
            else:
                logging.info(f"Análise para a conversa {conv_id} concluída e salva com sucesso.")
                
    except Exception as e:
        logging.error(f"Ocorreu um erro durante a análise em lote: {e}", exc_info=True)
    finally:
        db.close()
    
    logging.info("Análise em lote concluída. ✅")

if __name__ == "__main__":
    asyncio.run(main_async())