import logging
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from db import models

logger = logging.getLogger(__name__)


# --- Funções do Departamento de WhatsApp ---


def save_raw_conversation(
    db: Session,
    conversation_jid: str,
    messages: List[Dict[str, Any]],
) -> int:
    """
    Salva, de forma idempotente, as mensagens brutas de uma conversa do WhatsApp.

    - Encontra ou cria o registro da conversa.
    - Atualiza o timestamp da última mensagem na conversa.
    - Insere apenas mensagens novas, evitando duplicatas pelo `external_id`.
    - Retorna o número de novas mensagens inseridas.
    """
    # 1. Filtra mensagens inválidas e encontra o timestamp mais recente
    valid_messages = []
    latest_timestamp = 0
    for msg in messages:
        ts = msg.get("timestamp")
        if msg.get("external_id") and ts is not None:
            # Garante que ts seja um número antes de comparar
            try:
                current_ts = int(ts)
                valid_messages.append(msg)
                if current_ts > latest_timestamp:
                    latest_timestamp = current_ts
            except (ValueError, TypeError):
                continue  # Ignora mensagens com timestamp inválido

    if not valid_messages:
        return 0

    # 2. Encontra ou cria a conversa
    conversation = (
        db.query(models.WhatsappConversation)
        .filter_by(remote_jid=conversation_jid)
        .first()
    )
    if not conversation:
        conversation = models.WhatsappConversation(remote_jid=conversation_jid)
        db.add(conversation)
        db.flush()  # Garante que o conversation.id esteja disponível para as mensagens

    # 3. Atualiza o timestamp da conversa-pai
    if latest_timestamp > 0:
        conversation.last_message_timestamp = datetime.fromtimestamp(latest_timestamp)

    # 4. Prepara as mensagens para inserção em lote
    message_payloads = [
        {
            "conversation_id": conversation.id,
            "external_id": msg["external_id"],
            "sender": msg["sender"],
            "text": msg["text"],
            "message_timestamp": datetime.fromtimestamp(int(msg["timestamp"])),
            "message_type": msg.get("message_type"),
        }
        for msg in valid_messages
    ]

    if not message_payloads:
        db.commit()  # Commita a atualização do timestamp mesmo se não houver novas mensagens
        return 0

    # 5. Insere as mensagens usando `ON CONFLICT DO NOTHING` para garantir idempotência
    stmt = insert(models.WhatsappMessage).values(message_payloads)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["conversation_id", "external_id"]
    )

    try:
        result = db.execute(stmt)
        db.commit()
        inserted_count = result.rowcount
        logger.info(
            f"{inserted_count} novas mensagens salvas para a conversa {conversation_jid}"
        )
        return inserted_count
    except Exception as e:
        db.rollback()
        logger.error(
            f"Erro ao salvar mensagens para {conversation_jid}. Rollback executado. Erro: {e}"
        )
        return 0


def save_whatsapp_analysis_results(
    db: Session, conversation_jid: str, analysis_data: dict
):
    """
    Salva ou atualiza os resultados da análise de IA para uma conversa de WhatsApp.
    """
    conversation = (
        db.query(models.WhatsappConversation)
        .filter_by(remote_jid=conversation_jid)
        .first()
    )
    if not conversation:
        logger.error(
            f"Tentativa de salvar análise para conversa de WhatsApp inexistente: {conversation_jid}"
        )
        return

    analysis = (
        db.query(models.WhatsappAnalysis)
        .filter_by(conversation_id=conversation.id)
        .first()
    )
    if not analysis:
        analysis = models.WhatsappAnalysis(conversation_id=conversation.id)
        db.add(analysis)

    # Atualiza os campos da análise
    analysis.extracted_data = analysis_data.get("extracted_data")
    analysis.temperature_assessment = analysis_data.get("temperature_analysis")
    analysis.director_decision = analysis_data.get("director_decision")
    analysis.guard_report = analysis_data.get("guard_report")
    analysis.context = analysis_data.get("context")

    logger.info(
        f"Análise salva/atualizada para a conversa de WhatsApp {conversation_jid}."
    )
    db.commit()


# --- Funções do Departamento de E-mail ---


def save_email_analysis_results(db: Session, analysis_data: dict):
    """
    Salva ou atualiza os resultados da análise de IA para uma thread de e-mail.
    """
    email_thread_id = analysis_data.get("analysis_metadata", {}).get("email_thread_id")
    if not email_thread_id:
        logger.error("Tentativa de salvar análise de e-mail sem email_thread_id.")
        return

    analysis = (
        db.query(models.Analysis).filter_by(email_thread_id=email_thread_id).first()
    )
    if not analysis:
        # Verifica se a thread de email existe antes de criar a análise
        thread = db.query(models.EmailThread).filter_by(id=email_thread_id).first()
        if not thread:
            logger.error(f"Thread de e-mail com ID {email_thread_id} não encontrada.")
            return
        analysis = models.Analysis(email_thread_id=email_thread_id)
        db.add(analysis)

    # Atualiza todos os campos da análise
    analysis.extracted_data = analysis_data.get("extracted_data")
    analysis.temperature_assessment = analysis_data.get("temperature_analysis")
    analysis.director_decision = analysis_data.get("director_decision")
    analysis.kpis = analysis_data.get("kpis")
    analysis.advisor_recommendation = analysis_data.get("advisor_recommendation")
    analysis.context = analysis_data.get("context")
    analysis.formal_summary = analysis_data.get("formal_summary")

    logger.info(
        f"Análise completa salva/atualizada para a thread de e-mail {email_thread_id}."
    )
    db.commit()


# --- Funções de Consulta Genéricas ---


def get_latest_whatsapp_message_timestamp(db: Session) -> int:
    """Retorna o timestamp (epoch) da mensagem de WhatsApp mais recente no banco."""
    latest_timestamp = db.query(
        func.max(models.WhatsappMessage.message_timestamp)
    ).scalar()
    return int(latest_timestamp.timestamp()) if latest_timestamp else 0


def get_latest_email_message_timestamp(db: Session) -> int:
    """Retorna o timestamp (epoch) do e-mail mais recente no banco."""
    latest_datetime = db.query(func.max(models.EmailMessage.sent_datetime)).scalar()
    return int(latest_datetime.timestamp()) if latest_datetime else 0
