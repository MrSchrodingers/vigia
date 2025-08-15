import redis.asyncio as redis
import logging
import json
from typing import Optional

from vigia.config import settings

logger = logging.getLogger(__name__)

# --- Variável global para a instância do cliente ---
redis_client: Optional[redis.Redis] = None

def initialize_redis_client() -> Optional[redis.Redis]:
    """
    Cria e retorna uma instância do cliente Redis ASSÍNCRONO.
    Esta função é chamada uma vez quando o módulo é carregado.
    """
    try:
        # Usa um pool de conexões para eficiência
        connection_pool = redis.ConnectionPool.from_url(
            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
            decode_responses=False # O token do Jus.br é melhor tratado como bytes
        )
        client = redis.Redis(connection_pool=connection_pool)
        logger.info(f"Pool de conexões Redis criado com sucesso para {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        return client
    except Exception:
        logger.exception("Falha crítica ao criar o pool de conexões Redis.")
        return None

# --- Inicialização na importação do módulo ---
redis_client = initialize_redis_client()


# --- Funções Auxiliares Assíncronas para o Histórico de Conversas ---
CONVERSATION_TTL = 3600 

async def get_conversation_history(conversation_id: str) -> list[str]:
    """Busca o histórico de mensagens de uma conversa no Redis de forma assíncrona."""
    if not redis_client:
        logger.error("Cliente Redis não inicializado. Impossível buscar histórico.")
        return []
    
    history_bytes = await redis_client.get(conversation_id)
    
    if not history_bytes:
        return []
        
    try:
        return json.loads(history_bytes.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        logger.warning(f"Não foi possível decodificar o histórico para a conversa {conversation_id}.")
        return []

async def append_to_conversation_history(conversation_id: str, message: str):
    """Adiciona uma nova mensagem ao histórico de forma assíncrona."""
    if not redis_client:
        logger.error("Cliente Redis não inicializado. Impossível adicionar ao histórico.")
        return

    history = await get_conversation_history(conversation_id)
    history.append(message)
    history = history[-20:]
    
    history_bytes = json.dumps(history).encode('utf-8')
    
    await redis_client.set(conversation_id, history_bytes, ex=CONVERSATION_TTL)