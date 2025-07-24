from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # App
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    DATABASE_URL: str

    # --- LLM Settings ---
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    OLLAMA_API_URL: str = "http://host.docker.internal:11434"
    OLLAMA_MODEL: str = "llama3"
    
    # --- Evolution API Settings ---
    EVOLUTION_BASE_URL: str
    INSTANCE_NAME: str
    API_KEY: str
    
    # --- Pipedrive API Settings ---
    PIPEDRIVE_API_TOKEN: str = ""
    PIPEDRIVE_DOMAIN: str = ""
    
    # --- Redis Settings ---
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    
    # --- Celery Settings ---
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

settings = Settings()