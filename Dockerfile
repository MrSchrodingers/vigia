# ---------- 1. BUILD ---------------------------------------------------------
    FROM python:3.12-slim AS builder

    ENV PYTHONUNBUFFERED=1 \
        PIP_NO_CACHE_DIR=1 \
        POETRY_HOME=/opt/poetry \
        POETRY_VIRTUALENVS_CREATE=false \
        PATH="$POETRY_HOME/bin:$PATH"
    
    WORKDIR /app
    
    # --- sistema -----------------------------------------------------------------
    RUN apt-get update && \
        apt-get install -y --no-install-recommends build-essential curl git ffmpeg && \
        rm -rf /var/lib/apt/lists/*
    
    # --- wheels essenciais -------------------------------------------------------
    RUN pip install --upgrade pip wheel && \
        # 1) NumPy 1.x (compat‑torch)
        pip install "numpy<2" && \
        # 2) PyTorch/Audio CPU (builds para py3.12)
        pip install --no-deps \
            torch==2.2.2+cpu \
            torchaudio==2.2.2+cpu \
            --index-url https://download.pytorch.org/whl/cpu
    
    # --- Poetry ------------------------------------------------------------------
    RUN curl -sSL https://install.python-poetry.org | python3 - && \
        ln -s $POETRY_HOME/bin/poetry /usr/local/bin/poetry
    
    COPY pyproject.toml poetry.lock ./
    # instalamos tudo **exceto** o grupo 'whisper'
    RUN poetry install --only main --no-root --no-interaction --no-ansi

    # --- WebDriver Manager (para gerenciar o chromedriver) ---
        RUN pip install webdriver-manager selenium-wire setuptools 
    
    # --- Whisper (CPU) -----------------------------------------------------------
    RUN pip install --no-deps openai-whisper==20250625
    
    # ---------- 2. RUNTIME -------------------------------------------------------
    # ---------- 2. RUNTIME -------------------------------------------------------
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    unzip \
    libxi6 \
    ffmpeg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /etc/apt/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY ./vigia ./vigia
COPY ./db ./db
COPY ./lib ./lib
COPY ./alembic ./alembic
COPY ./alembic.ini ./
COPY ./docker-entrypoint.sh ./
COPY ./secrets ./secrets
COPY ./create_test_user.py ./

RUN chmod +x docker-entrypoint.sh

EXPOSE 8800
EXPOSE 8026

ENTRYPOINT ["./docker-entrypoint.sh"]