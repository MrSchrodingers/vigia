import asyncio
import logging
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional

from db.session import SessionLocal
from vigia.config import settings
from vigia.services import crud
from vigia.worker import celery_app

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate-limit distribuído (Redis) - janela deslizante
# ---------------------------------------------------------------------------
# Configurações via env (ou defaults):
_JUSBR_RL_MAX_PER_MINUTE = int(
    os.getenv("JUSBR_RL_MAX_PER_MINUTE", "30")
)  # total de req/min
_JUSBR_RL_PERIOD_SECONDS = 60
_JUSBR_RL_KEY_GLOBAL = os.getenv("JUSBR_RL_KEY_GLOBAL", "rl:jusbr:api:v2:processos")
_REDIS_URL = os.getenv(
    "REDIS_URL", getattr(settings, "REDIS_URL", "redis://redis:6379/0")
)
_JUSBR_TASK_RATE_LIMIT = os.getenv(
    "JUSBR_TASK_RATE_LIMIT", "30/m"
)  # Celery rate limit para a task

# Cliente Redis assíncrono (mesmo se Celery usar Redis, este cliente é independente)
try:
    from redis.asyncio import Redis  # type: ignore

    _redis_client: Optional[Redis] = None
except Exception:  # pragma: no cover - em caso de ambiente sem redis.asyncio
    Redis = None
    _redis_client = None


def _get_redis() -> Optional["Redis"]:
    global _redis_client
    if Redis is None:
        return None
    if _redis_client is None:
        _redis_client = Redis.from_url(_REDIS_URL, decode_responses=True)
    return _redis_client


async def _acquire_rate_limit(
    key: str,
    max_requests: int,
    period_seconds: int,
    timeout_seconds: int = 30,
) -> None:
    """
    Janela deslizante simples usando ZSET:
      - Remove entradas mais antigas que a janela
      - Se total < limite, adiciona uma nova marcação (timestamp ms)
      - Caso contrário, espera com jitter e tenta novamente

    Se 'timeout_seconds' expirar, levanta RuntimeError.
    """
    redis = _get_redis()
    if redis is None:
        # Se não houver Redis, não limita (fail-open), mas loga.
        logger.warning("Redis indisponível; prosseguindo sem rate-limit distribuído.")
        return

    deadline = time.monotonic() + timeout_seconds
    while True:
        now_ms = int(time.time() * 1000)
        window_start_ms = now_ms - (period_seconds * 1000)

        # Limpa janela e obtém contagem atual
        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, window_start_ms)
        pipe.zcard(key)
        removed, count = await pipe.execute()

        if count < max_requests:
            # Reserva slot
            member = f"{now_ms}:{os.getpid()}:{random.randint(0, 1_000_000_000)}"
            pipe = redis.pipeline()
            pipe.zadd(key, {member: now_ms})
            pipe.expire(key, period_seconds)
            await pipe.execute()
            return

        # Aguarda até liberar slot
        if time.monotonic() > deadline:
            raise RuntimeError("Timeout aguardando rate-limit global")
        # jitter 200–500ms
        await asyncio.sleep(0.2 + random.random() * 0.3)


def _is_celery_process() -> bool:
    return "celery" in " ".join(sys.argv).lower() or os.getenv("IS_CELERY", "") == "1"


# Singleton do PjeWorker apenas em processos Celery.
pje_worker_instance = None
if _is_celery_process():
    try:
        from vigia.services.pje_worker import PjeWorker

        pje_worker_instance = PjeWorker(
            cert_path=settings.PJE_PFX_PATH,
            cert_pass=settings.PJE_PFX_PASS,
            headless_port=settings.PJE_HEADLESS_PORT,
        )
    except Exception:
        logger.exception("Falha ao inicializar PjeWorker no processo Celery.")


def _recreate_singleton() -> None:
    global pje_worker_instance
    if pje_worker_instance is None:
        if not _is_celery_process():
            raise RuntimeError("PjeWorker não está disponível neste processo.")
        from vigia.services.pje_worker import PjeWorker  # import tardio

        pje_worker_instance = PjeWorker(
            cert_path=settings.PJE_PFX_PATH,
            cert_pass=settings.PJE_PFX_PASS,
            headless_port=settings.PJE_HEADLESS_PORT,
        )


@celery_app.task(
    name="jusbr.fetch_processo",
    queue="jusbr_work_queue",
    rate_limit=_JUSBR_TASK_RATE_LIMIT,  # Ex.: "30/m"
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def fetch_processo_task(numero_processo: str) -> Optional[Dict[str, Any]]:
    """
    Task que usa PjeWorker. Aplica rate-limit distribuído antes da chamada de rede.
    """
    # Gate global (mesmo com vários workers)
    asyncio.run(
        _acquire_rate_limit(
            key=_JUSBR_RL_KEY_GLOBAL,
            max_requests=_JUSBR_RL_MAX_PER_MINUTE,
            period_seconds=_JUSBR_RL_PERIOD_SECONDS,
        )
    )

    if pje_worker_instance is None:
        if not _is_celery_process():
            raise RuntimeError("PjeWorker não está disponível neste processo.")
        _recreate_singleton()

    logger.info("Buscando detalhes do processo %s via PjeWorker.", numero_processo)
    return asyncio.run(pje_worker_instance.process_task(numero_processo))


@celery_app.task(name="jusbr.refresh_login", queue="jusbr_control_queue")
def refresh_login_task() -> bool:
    if pje_worker_instance is None:
        if not _is_celery_process():
            raise RuntimeError("PjeWorker não está disponível neste processo.")
        _recreate_singleton()
    return pje_worker_instance.refresh_and_store_token()


@celery_app.task(
    name="tasks.sync_jusbr_for_process",
    rate_limit=_JUSBR_TASK_RATE_LIMIT,  # Ex.: "30/m"
    autoretry_for=(RuntimeError,),  # re-tenta throttling/timeout
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def sync_jusbr_for_process_task(process_number: str, user_id: str) -> Dict[str, Any]:
    """
    Busca dados no PDJ e persiste no banco.
    - Rate-limit distribuído antes de chamar a API do PDJ
    - Autoretry com backoff + jitter se detectar throttling (HTTP 429)
    """
    logging.info(
        "[TASK] Iniciando sincronização Jus.br para o processo: %s", process_number
    )
    from vigia.services.jusbr_service import jusbr_service

    # Gate global (janela deslizante em Redis)
    asyncio.run(
        _acquire_rate_limit(
            key=_JUSBR_RL_KEY_GLOBAL,
            max_requests=_JUSBR_RL_MAX_PER_MINUTE,
            period_seconds=_JUSBR_RL_PERIOD_SECONDS,
        )
    )

    db = SessionLocal()
    saved = 0
    try:
        jusbr_data_list: Optional[List[Dict[str, Any]]] = asyncio.run(
            jusbr_service.get_processo_details_with_docs(process_number)
        )

        if not jusbr_data_list:
            logging.error("[TASK] Resposta vazia para %s", process_number)
            return {"process_number": process_number, "saved": 0, "reason": "empty"}

        # Alguns fluxos retornam [{'erro': '...'}]
        if (
            isinstance(jusbr_data_list, list)
            and jusbr_data_list
            and jusbr_data_list[0].get("erro")
        ):
            error_msg = str(jusbr_data_list[0].get("erro", "Erro desconhecido"))
            logging.error(
                "[TASK] Erro do Jus.br para %s: %s", process_number, error_msg
            )

            # Se for throttling (HTTP 429), forçamos retry com backoff:
            if "429" in error_msg:
                raise RuntimeError("HTTP 429 (Too Many Requests)")

            return {"process_number": process_number, "saved": 0, "reason": error_msg}

        for process_data in jusbr_data_list:
            crud.upsert_process_from_jusbr_data(db, process_data, user_id=user_id)
            saved += 1

        db.commit()
        logging.info(
            "[TASK] Sincronização Jus.br para %s concluída. saved=%d",
            process_number,
            saved,
        )
        return {"process_number": process_number, "saved": saved}
    except Exception as e:
        logging.error(
            "[TASK] Falha crítica na tarefa de sincronização para %s: %s",
            process_number,
            e,
            exc_info=True,
        )
        raise
    finally:
        try:
            db.close()
        except Exception:
            logging.exception(
                "Erro ao fechar sessão DB em sync_jusbr_for_process_task."
            )
