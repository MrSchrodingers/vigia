import logging
from sqlalchemy.orm import Session
from datetime import datetime

from db import models

logger = logging.getLogger(__name__)

# --- Funções do Departamento de WhatsApp ---
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
    
def save_raw_conversation(db: Session, conversation_jid: str, messages: list[dict]):
    """
    Salva de forma idempotente as mensagens brutas de uma conversa de WhatsApp.
    Usado pelo importador histórico do WhatsApp.
    """
    # Encontra ou cria a conversa
    conversation = db.query(models.Conversation).filter_by(remote_jid=conversation_jid).first()
    if not conversation:
        conversation = models.Conversation(remote_jid=conversation_jid)
        db.add(conversation)
        # O flush é importante para obter o conversation.id antes do commit final
        db.flush()

    incoming_external_ids = {msg['external_id'] for msg in messages if msg.get('external_id')}
    
    if not incoming_external_ids:
        return # Nenhuma mensagem com ID para processar

    # Busca no banco quais desses IDs já existem para esta conversa
    existing_ids = {
        res[0] for res in db.query(models.Message.external_id)
        .filter(models.Message.conversation_id == conversation.id)
        .filter(models.Message.external_id.in_(incoming_external_ids))
        .all()
    }
    
    # Adiciona apenas as mensagens que ainda não existem
    new_messages_added = False
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
            new_messages_added = True
    
    if new_messages_added:
        db.commit()

def save_whatsapp_analysis_results(
    db: Session,
    conversation_jid: str,
    analysis_data: dict
):
    """
    Salva ou atualiza os resultados da análise de IA para uma conversa de WhatsApp.
    Usa o modelo de análise polimórfico.
    """
    conversation = db.query(models.Conversation).filter_by(remote_jid=conversation_jid).first()
    if not conversation:
        logger.error(f"Tentativa de salvar análise para conversa de WhatsApp inexistente: {conversation_jid}")
        return

    # Encontra ou cria a análise usando a chave polimórfica
    analysis = db.query(models.Analysis).filter_by(
        analysable_id=str(conversation.id), 
        analysable_type='conversation'
    ).first()
    
    if not analysis:
        analysis = models.Analysis(
            analysable_id=str(conversation.id),
            analysable_type='conversation'
        )
        db.add(analysis)

    # Atualiza os dados da análise
    analysis.extracted_data = analysis_data.get("extracted_data")
    analysis.temperature_assessment = analysis_data.get("temperature_analysis")
    analysis.director_decision = analysis_data.get("director_decision")
    
    logger.info(f"Análise atualizada para a conversa de WhatsApp {conversation_jid}.")
    db.commit()

# --- Funções do Departamento de E-mail ---
def save_email_analysis_results(db: Session, analysis_data: dict):
    """
    Salva ou atualiza os resultados da análise de IA para uma thread de e-mail.
    Usa o modelo de análise polimórfico.
    """
    conversation_id = analysis_data.get("analysis_metadata", {}).get("conversation_id")
    if not conversation_id:
        logger.error("Tentativa de salvar análise de e-mail sem conversation_id.")
        return

    thread = db.query(models.EmailThread).filter_by(conversation_id=conversation_id).first()
    if not thread:
        logger.error(f"Tentativa de salvar análise para thread de e-mail inexistente: {conversation_id}")
        return

    # Encontra ou cria a análise usando a chave polimórfica
    analysis = db.query(models.Analysis).filter_by(
        analysable_id=str(thread.id), 
        analysable_type='email_thread'
    ).first()

    if not analysis:
        analysis = models.Analysis(
            analysable_id=str(thread.id),
            analysable_type='email_thread'
        )
        db.add(analysis)

    # Atualiza os dados da análise
    analysis.extracted_data = analysis_data.get("extracted_data")
    analysis.temperature_assessment = analysis_data.get("temperature_analysis")
    analysis.director_decision = analysis_data.get("director_decision")
    
    logger.info(f"Análise atualizada para a thread de e-mail {conversation_id}.")
    db.commit()

# --- Funções de Consulta Genéricas ---
def get_latest_whatsapp_message_timestamp(db: Session) -> int:
    """Retorna o timestamp da mensagem de WhatsApp mais recente no banco."""
    latest_message = db.query(models.Message).order_by(models.Message.message_timestamp.desc()).first()
    return int(latest_message.message_timestamp.timestamp()) if latest_message else 0

def get_latest_email_message_timestamp(db: Session) -> int:
    """Retorna o timestamp do e-mail mais recente no banco."""
    latest_email = db.query(models.EmailMessage).order_by(models.EmailMessage.sent_datetime.desc()).first()
    return int(latest_email.sent_datetime.timestamp()) if latest_email else 0