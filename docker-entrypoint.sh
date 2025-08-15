#!/usr/bin/env bash
set -e

echo "===== ENTRYPOINT VIGIA ====="
export PATH="/opt/venv/bin:${PATH}"
alembic upgrade head

case "$ROLE" in
  api)
      echo "🚀 Celery (fila genérica + JusBR)"
      celery -A vigia.worker.celery_app worker \
             --queues=celery,jusbr_work_queue --loglevel=info &
      echo "🚀 Uvicorn"
      exec uvicorn vigia.main_api:app --host 0.0.0.0 --port 8026 --reload --reload-dir vigia
      ;;
  pje|pje-worker)
      echo "🚀 PJe worker headless"
      exec python -u vigia/services/pje_worker.py
      ;;
  worker)
      echo "🚀 Celery (worker genérico)"
      exec celery -A vigia.worker.celery_app worker --loglevel=info
      ;;
  *)
      echo "ROLE desconhecido: $ROLE"
      exit 2
      ;;
esac