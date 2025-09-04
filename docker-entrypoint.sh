#!/usr/bin/env bash
set -e

echo "===== ENTRYPOINT VIGIA ====="

# ❌ Remova isso se não há venv:
# export PATH="/opt/venv/bin:${PATH}"

# ⚠️ Rode migração só quando apropriado (ver seção 2)
if [ "${RUN_DB_MIGRATIONS:-false}" = "true" ]; then
  echo "▶ Running Alembic migrations..."
  alembic upgrade head
fi

case "$ROLE" in
  api)
      echo "🚀 Celery (fila genérica + JusBR)"
      celery -A vigia.worker.celery_app worker \
             --queues=celery,jusbr_work_queue,jusbr_control_queue --loglevel=info &
      echo "🚀 Uvicorn"
      exec uvicorn vigia.main_api:app --host 0.0.0.0 --port 8026
      ;;
  pje|pje-worker)
      echo "🚀 PJe worker headless"
      exec python -u -m vigia.services.pje_worker
      ;;
  worker)
      echo "🚀 Celery (worker genérico)"
      # ✅ sem poetry:
      exec celery -A vigia.worker.celery_app worker -l info -Q jusbr_work_queue,jusbr_control_queue -c 1
      ;;
  *)
      echo "ROLE desconhecido: $ROLE"
      exit 2
      ;;
esac
