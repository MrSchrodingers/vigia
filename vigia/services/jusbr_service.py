import logging
import asyncio
from typing import Dict, Any, Optional
from celery.result import AsyncResult  # noqa: F401
import httpx

from vigia.worker import celery_app  # noqa: F401
from vigia.tasks.jusbr_tasks import fetch_processo_task

logger = logging.getLogger(__name__)

class JusbrService:
    """Fachada assíncrona que dispara a task Celery e espera pelo resultado."""
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
      self.client = client 

    async def get_processo_details_with_docs(
        self, numero_processo: str, timeout: int = 500
    ) -> Optional[Dict[str, Any]]:

        numero = "".join(filter(str.isdigit, numero_processo))
        async_result = fetch_processo_task.apply_async(
            args=[numero],
            queue="jusbr_work_queue",
            routing_key="jusbr",
        )
        logger.info(
            "Task Celery 'jusbr.fetch_processo' publicada "
            f"(task_id={async_result.id}, processo={numero})."
        )

        try:
            result = await asyncio.to_thread(async_result.get, timeout=timeout)
            return result
        except Exception as exc:
            logger.error(
                "Falha ou timeout esperando task %s: %s", async_result.id, exc
            )
            return None

jusbr_service = JusbrService(client=httpx.AsyncClient(timeout=30))
