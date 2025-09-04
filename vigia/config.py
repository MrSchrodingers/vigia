from __future__ import annotations

import ast
from typing import Any, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _parse_list(value: Any) -> List[str]:
    """
    Aceita:
      • string “a,b,c”
      • string '["a","b"]'
      • lista real
    Retorna sempre list[str] sem espaços nem vazios.
    """
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str) and value:
        value = value.strip()
        try:                      # tenta JSON / Python-list first
            parsed = ast.literal_eval(value)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (ValueError, SyntaxError):
            pass
        # fallback “a,b,c”
        return [item.strip() for item in value.split(",") if item.strip()]

    return []


class Settings(BaseSettings):
    """
    Configurações globais da aplicação VigIA.
    Carrega variáveis do sistema + arquivo `.env`.
    """

    # ───── Config interna do Pydantic ─────────────────────────
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,      # ← imutável depois de criada
    )

    # ───────────────────── App / Runtime ──────────────────────
    ENVIRONMENT: str = Field(default="development")
    LOG_LEVEL: str = Field(default="INFO")
    
    # JWT / Auth  ← NOVO
    SECRET_KEY: str 
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int

    # UID/GID opcionais (usados no docker-compose para mapear volumes)
    UID: int | None = None
    GID: int | None = None

    # ─────────── Banco de Dados (PostgreSQL) ────────────
    DATABASE_URL: str

    # ───────────── Redis / Celery ──────────────
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # ────────────── PJe Office (headless) ───────────────
    PJE_PFX_PASS: str
    PJE_PFX_PATH: str 
    PJE_HEADLESS_PORT: int
    
    # ────────────── Jus.br PDPJ ───────────────
    JUSBR_API_BASE_URL: str
    JUSBR_CLIENT_ID: str
    JUSBR_REDIRECT_URI: str
    JUSBR_AUTH_TOKEN_EXPIRATION_SECONDS: int = 3000  # 50 min

    # ───────────── LLM Providers ──────────────
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str | None = None
    OLLAMA_API_URL: str | None = None
    OLLAMA_MODEL: str | None = None

    # ───────── Evolution / WhatsApp ───────────
    EVOLUTION_BASE_URL: str
    INSTANCE_NAME: str
    API_KEY: str

    # ────────────── CRM (Pipedrive) ───────────
    PIPEDRIVE_DOMAIN: str
    PIPEDRIVE_API_TOKEN_WHATSAPP: str
    PIPEDRIVE_API_TOKEN_EMAIL: str

    # ────────────── Graph / Email ─────────────
    GRAPH_BASE_URL: str = "https://graph.microsoft.com/v1.0"
    TENANT_ID: str
    CLIENT_ID: str
    CLIENT_SECRET: str

    SENT_FOLDER_NAME: str = "itens enviados"
    IGNORE_SUBJECT_PREFIXES: str = "RES:,ENC:,FWD:,FW:"

    EMAIL_ACCOUNTS: List[str] = Field(default_factory=list)
    SUBJECT_FILTER: List[str] = Field(default_factory=list)
    IGNORED_RECIPIENT_PATTERNS: List[str] = Field(default_factory=list)

    # ────────────── Validadores custom ─────────────
    @field_validator(
        "EMAIL_ACCOUNTS",
        "SUBJECT_FILTER",
        "IGNORED_RECIPIENT_PATTERNS",
        mode="before",
    )
    @classmethod
    def _to_list(cls, v: Any) -> List[str]:
        return _parse_list(v)

    @field_validator("REDIS_PORT", "REDIS_DB", mode="before")
    @classmethod
    def _to_int(cls, v: Any) -> int:
        """
        Permite que portas / DB venham como string, converte para int.
        """
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
        raise ValueError("deve ser número inteiro")

settings = Settings()
