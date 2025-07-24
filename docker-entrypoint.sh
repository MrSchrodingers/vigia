#!/bin/sh
set -e
echo "===== ENTRYPOINT: Iniciando processos de inicialização ====="

# 1) Aplicando a migrações Alembic:
echo "🚀 Aplicando a migração para criar as tabelas no banco de dados..."
python -m alembic upgrade head

# 2) Inicia Aplicação:
echo "🚀 Iniciando Aplicação!"
python -m uvicorn vigia.main_api:app --host 0.0.0.0 --port 8026 --reload --reload-dir dashboard/ --reload-dir vigia/ --reload-dir scripts/

echo "===== ENTRYPOINT: Aplicação Inciada! ====="