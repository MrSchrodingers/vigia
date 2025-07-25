# --- Estágio de Build ---
    FROM python:3.12-slim AS builder

    ENV PYTHONUNBUFFERED=1 \
        PIP_NO_CACHE_DIR=1 \
        POETRY_HOME="/opt/poetry" \
        POETRY_VIRTUALENVS_CREATE=false
    
    ENV PATH="${POETRY_HOME}/bin:${PATH}"
    
    WORKDIR /app
    
    RUN apt-get update && \
        apt-get install -y --no-install-recommends build-essential libpq-dev curl && \
        curl -sSL https://install.python-poetry.org | python3 - && \
        poetry --version && \
        poetry config virtualenvs.create false && \
        apt-get purge -y --auto-remove build-essential curl && \
        rm -rf /var/lib/apt/lists/*
    
    COPY pyproject.toml poetry.lock ./
    RUN poetry install --no-interaction --no-ansi --only main --no-root
    
    
    # --- Estágio de Runtime ---
    FROM python:3.12-slim AS runtime
    
    ENV PYTHONUNBUFFERED=1 \
        APP_USER=appuser
    
    WORKDIR /app
    
    RUN apt-get update && \
        apt-get install -y --no-install-recommends libpq5 && \
        rm -rf /var/lib/apt/lists/* && \
        groupadd -r ${APP_USER} && \
        useradd --no-log-init -r -g ${APP_USER} ${APP_USER}
    
    # Copia as dependências e binários instalados
    COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
    COPY --from=builder /usr/local/bin /usr/local/bin
    
    # Copia o código da aplicação
    COPY ./vigia ./vigia
    
    # Copia entrypoint Docker de Migrations
    COPY docker-entrypoint.sh docker-entrypoint.sh
    RUN chmod +x docker-entrypoint.sh

    RUN chown -R ${APP_USER}:${APP_USER} /app
    USER ${APP_USER}
    
    EXPOSE 8026
    CMD ["python", "-m", "uvicorn", "vigia.main_api:app", "--host", "0.0.0.0", "--port", "8026"]
    