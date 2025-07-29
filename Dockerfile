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
        apt-get install -y --no-install-recommends build-essential curl git && \
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
    
    # --- Whisper (CPU) -----------------------------------------------------------
    RUN pip install --no-deps openai-whisper==20250625
    
    # ---------- 2. RUNTIME -------------------------------------------------------
    FROM python:3.12-slim
    
    RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
        rm -rf /var/lib/apt/lists/*
    
    WORKDIR /app
    COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
    COPY --from=builder /usr/local/bin /usr/local/bin
    COPY ./vigia ./vigia
    
    EXPOSE 8026
    CMD ["python", "-m", "uvicorn", "vigia.main_api:app", "--host", "0.0.0.0", "--port", "8026"]
    