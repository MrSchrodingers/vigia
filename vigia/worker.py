import asyncio
from celery import Celery
from .config import settings
from vigia.core.general_orchestrator import route_to_department
import logging

logging.basicConfig(level=settings.LOG_LEVEL)

celery_app = Celery(
    "vigia_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)
celery_app.conf.update(task_track_started=True)

@celery_app.task(name="process_conversation_task")
def process_conversation_task(payload: dict):
    """
    Tarefa do Celery que chama o Diretor-Geral para rotear a análise.
    """
    conversation_id = payload.get("conversation_id", payload.get("id", "ID não fornecido"))
    source = payload.get("source", "Fonte desconhecida")
    
    logging.info(f"Processando tarefa para a conversa: {conversation_id} (Fonte: {source})")
    try:
        # O worker agora chama o orquestrador geral (Diretor-Geral)
        asyncio.run(route_to_department(payload))
    except Exception as e:
        logging.error(f"Erro ao processar a tarefa para {conversation_id}: {e}", exc_info=True)