import redis
import json
from ..config import settings

# Conexão global para reutilização
redis_client = redis.Redis(
    host=settings.REDIS_HOST, 
    port=settings.REDIS_PORT, 
    db=settings.REDIS_DB, 
    decode_responses=True
)

CONVERSATION_TTL = 3600 # Guarda o histórico por 1 hora

def get_conversation_history(conversation_id: str) -> list[str]:
    """Busca o histórico de mensagens de uma conversa no Redis."""
    history_json = redis_client.get(conversation_id)
    return json.loads(history_json) if history_json else []

def append_to_conversation_history(conversation_id: str, message: str):
    """Adiciona uma nova mensagem ao histórico e renova o tempo de expiração."""
    history = get_conversation_history(conversation_id)
    history.append(message)
    # Mantém apenas as últimas 20 mensagens para não sobrecarregar o prompt
    history = history[-20:] 
    redis_client.set(conversation_id, json.dumps(history), ex=CONVERSATION_TTL)