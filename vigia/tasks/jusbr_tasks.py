import os
import asyncio
from vigia.worker import celery_app
from vigia.services.pje_worker import PjeWorker

PJE_PFX_PATH = os.getenv("PJE_PFX")
PJE_PFX_PASS = os.getenv("PJE_PFX_PASS")
PJE_HEADLESS_PORT = int(os.getenv("PJE_HEADLESS_PORT", 8800))

# Instancia o worker uma vez por processo Celery
pje_worker_instance = PjeWorker(
    cert_path=PJE_PFX_PATH, 
    cert_pass=PJE_PFX_PASS, 
    headless_port=PJE_HEADLESS_PORT
)


@celery_app.task(
    name="jusbr.fetch_processo",
    queue="jusbr_work_queue",
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def fetch_processo_task(numero_processo: str) -> dict | None:
    """
    Tarefa Celery que executa a lógica de busca de processo do PjeWorker.
    """
    return asyncio.run(pje_worker_instance.process_task(numero_processo))


@celery_app.task(
    name="jusbr.refresh_login",
    queue="jusbr_control_queue",
)
def refresh_login_task() -> bool:
    """
    Tarefa Celery que força a renovação do token de login do Jus.br.
    """
    return pje_worker_instance.refresh_and_store_token()
