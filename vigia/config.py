from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Any

class Settings(BaseSettings):
    """
    Configurações centralizadas para a aplicação VigIA.
    Lê variáveis de um arquivo .env e do ambiente do sistema.
    """
    # Configuração do Pydantic
    model_config = SettingsConfigDict(
        env_file='.env', 
        env_file_encoding='utf-8', 
        extra='ignore'
    )

    # App
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    
    # Banco de Dados
    DATABASE_URL: str

    # --- Serviços de LLM ---
    LLM_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    OLLAMA_API_URL: str = "http://host.docker.internal:11434"
    OLLAMA_MODEL: str = "llama3"
    
    # --- WhatsApp (Evolution API) ---
    EVOLUTION_BASE_URL: str
    INSTANCE_NAME: str
    API_KEY: str
    
    # --- CRM (Pipedrive) ---
    PIPEDRIVE_API_TOKEN_WHATSAPP: str = ""
    PIPEDRIVE_API_TOKEN_EMAIL: str = ""
    PIPEDRIVE_DOMAIN: str = ""
    
    # --- E-mail (Microsoft Graph API) ---
    GRAPH_BASE_URL: str = "https://graph.microsoft.com/v1.0"
    TENANT_ID: str = ""
    CLIENT_ID: str = ""
    CLIENT_SECRET: str = ""
    
    # Campos que precisam ser convertidos de string para lista
    EMAIL_ACCOUNTS: List[str] = []
    SUBJECT_FILTER: List[str] = []
    IGNORED_RECIPIENT_PATTERNS: List[str] = []
    
    SENT_FOLDER_NAME: str = "Itens Enviados"
    IGNORE_SUBJECT_PREFIXES: str = "RES:,ENC:,FWD:,FW:"
    
    # --- Background Jobs (Redis & Celery) ---
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    @field_validator('EMAIL_ACCOUNTS', 'SUBJECT_FILTER', 'IGNORED_RECIPIENT_PATTERNS', mode='before')
    @classmethod
    def _split_str_to_list(cls, v: Any) -> List[str]:
        """
        Validador que converte uma string separada por vírgulas,
        recebida do arquivo .env, em uma lista de strings.
        Isso é executado ANTES da validação padrão do Pydantic, evitando o erro de JSON.
        """
        if isinstance(v, str) and v:
            return [item.strip() for item in v.split(',') if item.strip()]
        if isinstance(v, list):
            return v
        return []

settings = Settings()