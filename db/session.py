import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from vigia.config import settings

def custom_json_serializer(*args, **kwargs) -> str:
    """
    Função de serialização customizada que garante que caracteres
    especiais (não-ASCII) sejam preservados.
    """
    return json.dumps(*args, ensure_ascii=False, **kwargs)
  
engine = create_engine(
    settings.DATABASE_URL,
    json_serializer=custom_json_serializer,
    connect_args={"client_encoding": "utf8"}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)