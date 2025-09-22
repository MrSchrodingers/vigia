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
    instance_name: str,
    conversation_jid: str,
    messages: List[Dict[str, Any]],
) -> int:
    valid_messages = []
    latest_timestamp = 0
    earliest_timestamp = None
    for msg in messages:
        ts = msg.get("timestamp")
        if msg.get("external_id") and ts is not None:
            try:
                current_ts = int(ts)
                valid_messages.append(msg)
                if earliest_timestamp is None or current_ts < earliest_timestamp:
                    earliest_timestamp = current_ts
                if current_ts > latest_timestamp:
                    latest_timestamp = current_ts
            except (ValueError, TypeError):
                continue

    discarded = len(messages) - len(valid_messages)
    if not valid_messages:
        logger.info(
            "[%s|%s] Nenhuma mensagem válida (descartadas=%s).",
            instance_name,
            conversation_jid,
            discarded,
        )
        return 0

    conversation = (
        db.query(models.WhatsappConversation)
        .filter_by(instance_name=instance_name, remote_jid=conversation_jid)
        .first()
    )
    created = False
    if not conversation:
        conversation = models.WhatsappConversation(
            instance_name=instance_name,
            remote_jid=conversation_jid,
        )
        db.add(conversation)
        db.flush()
        created = True

    if latest_timestamp > 0:
        conversation.last_message_timestamp = datetime.fromtimestamp(latest_timestamp)

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
        db.commit()
        logger.info(
            "[%s|%s] Sem payload após validação; apenas atualizei last_message_timestamp.",
            instance_name,
            conversation_jid,
        )
        return 0

    stmt = insert(models.WhatsappMessage).values(message_payloads)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["conversation_id", "external_id"]
    )

    try:
        result = db.execute(stmt)
        db.commit()
        inserted_count = result.rowcount or 0
        logger.info(
            "[%s|%s] %s | msgs_validas=%s descartadas=%s intervalo=[%s → %s] inserts=%s",
            instance_name,
            conversation_jid,
            "CRIADA" if created else "REUTILIZADA",
            len(valid_messages),
            discarded,
            datetime.fromtimestamp(earliest_timestamp).isoformat()
            if earliest_timestamp
            else "-",
            datetime.fromtimestamp(latest_timestamp).isoformat()
            if latest_timestamp
            else "-",
            inserted_count,
        )
        return inserted_count
    except Exception as e:
        db.rollback()
        logger.error(
            "[%s|%s] Erro ao salvar mensagens. Rollback. Erro: %s",
            instance_name,
            conversation_jid,
            e,
        )
        return 0


def save_whatsapp_analysis_results(
    db: Session, instance_name: str, conversation_jid: str, analysis_data: dict
):
    """
    Salva/atualiza resultados da análise de IA para uma conversa (chave: instância + JID).
    """
    conversation = (
        db.query(models.WhatsappConversation)
        .filter_by(instance_name=instance_name, remote_jid=conversation_jid)
        .first()
    )
    if not conversation:
        conversation = (
            db.query(models.WhatsappConversation)
            .filter_by(remote_jid=conversation_jid)
            .first()
        )

    if not conversation:
        logger.error(
            f"[{instance_name}] Tentativa de salvar análise para conversa inexistente: {conversation_jid}"
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

    analysis.extracted_data = analysis_data.get("extracted_data")
    analysis.temperature_assessment = analysis_data.get("temperature_analysis")
    analysis.director_decision = analysis_data.get("director_decision")
    analysis.guard_report = analysis_data.get("guard_report")
    analysis.context = analysis_data.get("context")

    logger.info(
        f"[{instance_name}] Análise salva/atualizada para a conversa {conversation_jid}."
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
