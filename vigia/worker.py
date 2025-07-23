import asyncio
from celery import Celery
from .config import settings
from vigia.core.orchestrator import run_multi_agent_cycle_async
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
    """Tarefa do Celery que inicia o ciclo de processamento do agente."""
    conversation_id = payload.get("conversation_id", "ID não fornecido")
    logging.info(f"Processando tarefa para a conversa: {conversation_id}")
    try:
        asyncio.run(run_multi_agent_cycle_async(payload))
    except Exception as e:
        logging.error(f"Erro ao processar a tarefa para {conversation_id}: {e}", exc_info=True)