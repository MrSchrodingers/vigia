import os
import sys
import asyncio
from vigia.config import settings
from vigia.worker import celery_app
from vigia.services.pje_worker import PjeWorker

def _is_celery_process() -> bool:
    return "celery" in " ".join(sys.argv).lower() or os.getenv("IS_CELERY", "") == "1"

pje_worker_instance = None
if _is_celery_process():
    pje_worker_instance = PjeWorker(
        cert_path=settings.PJE_PFX_PATH,
        cert_pass=settings.PJE_PFX_PASS,
        headless_port=settings.PJE_HEADLESS_PORT,
    )

@celery_app.task(
    name="jusbr.fetch_processo",
    queue="jusbr_work_queue",
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def fetch_processo_task(numero_processo: str) -> dict | None:
    if pje_worker_instance is None:
        if not _is_celery_process():
            raise RuntimeError("PjeWorker não está disponível neste processo.")
        _recreate_singleton()
    return asyncio.run(pje_worker_instance.process_task(numero_processo))

def _recreate_singleton():
    global pje_worker_instance
    if pje_worker_instance is None:
        pje_worker_instance = PjeWorker(
            cert_path=settings.PJE_PFX_PATH,
            cert_pass=settings.PJE_PFX_PASS,
            headless_port=settings.PJE_HEADLESS_PORT,
        )

@celery_app.task(name="jusbr.refresh_login", queue="jusbr_control_queue")
def refresh_login_task() -> bool:
    if pje_worker_instance is None:
        if not _is_celery_process():
            raise RuntimeError("PjeWorker não está disponível neste processo.")
        _recreate_singleton()
    return pje_worker_instance.refresh_and_store_token()
