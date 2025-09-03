import asyncio
import logging
import redis
from typing import Optional, Dict, Any

from vigia.config import settings
from vigia.tasks.jusbr_tasks import fetch_processo_task, refresh_login_task

logger = logging.getLogger(__name__)

class JusbrService:
    """
    Fachada para interagir com os serviços do Jus.br.
    - Verifica o status do login via Redis.
    - Dispara tarefas de atualização de login e busca de processos via Celery.
    """
    def __init__(self):
        try:
            self.redis_conn = redis.Redis(
                host=settings.REDIS_HOST, 
                port=settings.REDIS_PORT, 
                db=0,
                socket_connect_timeout=2
            )
            self.redis_conn.ping()
            logger.info("Conexão com Redis estabelecida para JusbrService.")
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Não foi possível conectar ao Redis: {e}")
            self.redis_conn = None

    async def check_login_status(self) -> bool:
        """
        Verifica se o token de login do Jus.br existe e é válido no Redis.
        """
        if not self.redis_conn:
            return False
        try:
            token_exists = self.redis_conn.exists("jusbr:bearer_token")
            return bool(token_exists)
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Erro ao verificar status no Redis: {e}")
            return False

    async def refresh_login(self):
        """
        Dispara uma tarefa em background (Celery) para forçar um novo login no Jus.br.
        A API responde imediatamente, e o worker faz o trabalho pesado.
        """
        logger.info("Disparando tarefa Celery 'jusbr.refresh_login'...")
        refresh_login_task.apply_async(queue="jusbr_control_queue")
    
    async def get_processo_details_with_docs(
        self, numero_processo: str, timeout: int = 500
    ) -> Optional[Dict[str, Any]]:
        """
        Dispara a task Celery para buscar um processo e aguarda pelo resultado.
        """
        numero = "".join(filter(str.isdigit, numero_processo))
        async_result = fetch_processo_task.apply_async(
            args=[numero],
            queue="jusbr_work_queue",
        )
        logger.info(
            f"Task Celery 'jusbr.fetch_processo' publicada (task_id={async_result.id})."
        )

        try:
            # Usamos to_thread para não bloquear o event loop do FastAPI enquanto espera
            result = await asyncio.to_thread(async_result.get, timeout=timeout)
            return result
        except Exception as exc:
            logger.error(f"Falha ou timeout esperando task {async_result.id}: {exc}")
            return None

# Instância única para ser usada na aplicação
jusbr_service = JusbrService()