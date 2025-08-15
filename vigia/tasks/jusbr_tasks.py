import redis
import json
import uuid
from vigia.worker import celery_app

@celery_app.task(
    name="jusbr.fetch_processo",
    queue="jusbr_work_queue",
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def fetch_processo_task(numero_processo: str) -> dict|None:
    redis_conn = redis.Redis(host="redis", port=6379, db=0)
    result_key = f"jusbr_result:{uuid.uuid4()}"
    payload = {"numero_processo": numero_processo, "result_key": result_key}
    redis_conn.rpush("jusbr_work_queue", json.dumps(payload))
    # espera a resposta (máx. 150 s)
    res = redis_conn.blpop(result_key, timeout=150)
    if not res:
        raise RuntimeError("Timeout esperando worker PJe.")
    return json.loads(res[1])
