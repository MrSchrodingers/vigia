import logging
from sqlalchemy.orm import Session
from datetime import datetime

from db import models

def save_raw_conversation(db: Session, conversation_jid: str, messages: list[dict]):
    """
    Salva de forma idempotente as mensagens brutas de uma conversa.
    Esta função é usada pelo importador.
    """
    # Encontra ou cria a conversa
    conversation = db.query(models.Conversation).filter_by(remote_jid=conversation_jid).first()
    if not conversation:
        conversation = models.Conversation(remote_jid=conversation_jid)
        db.add(conversation)
        db.flush()

    # Pega todos os IDs externos das novas mensagens
    incoming_external_ids = {msg['external_id'] for msg in messages if msg.get('external_id')}
    
    # Busca no banco quais desses IDs já existem para esta conversa
    existing_ids = {
        res[0] for res in db.query(models.Message.external_id)
        .filter(models.Message.conversation_id == conversation.id)
        .filter(models.Message.external_id.in_(incoming_external_ids))
        .all()
    }
    
    # Adiciona apenas as mensagens que ainda não existem
    for msg_data in messages:
        external_id = msg_data.get('external_id')
        if external_id and external_id not in existing_ids:
            message = models.Message(
                external_id=external_id,
                conversation_id=conversation.id,
                sender=msg_data['sender'],
                text=msg_data['text'],
                message_timestamp=datetime.fromtimestamp(msg_data['timestamp'])
            )
            db.add(message)
    
    db.commit()
    
def save_analysis_results(
    db: Session,
    conversation_jid: str,
    messages: list[dict],
    extracted_data: dict,
    temp_assessment: dict,
    director_decision: dict
):
    """
    Salva ou atualiza os resultados da análise de IA para uma conversa.
    Esta função é usada pelo worker após o processamento.
    """
    conversation = db.query(models.Conversation).filter_by(remote_jid=conversation_jid).first()
    if not conversation:
        logging.error(f"Tentativa de salvar análise para conversa inexistente: {conversation_jid}")
        return

    # Encontra ou cria a análise
    analysis = db.query(models.Analysis).filter_by(conversation_id=conversation.id).first()
    if not analysis:
        analysis = models.Analysis(conversation_id=conversation.id)
        db.add(analysis)

    # Atualiza os dados da análise
    analysis.extracted_data = extracted_data
    analysis.temperature_assessment = temp_assessment
    analysis.director_decision = director_decision
    logging.info(f"Análise atualizada para a conversa {conversation_jid}.")

    db.commit()

def get_latest_message_timestamp(db: Session) -> int:
    """Retorna o timestamp da mensagem mais recente no banco de dados."""
    latest_message = db.query(models.Message).order_by(models.Message.message_timestamp.desc()).first()
    if latest_message:
        return int(latest_message.message_timestamp.timestamp())
    return 0