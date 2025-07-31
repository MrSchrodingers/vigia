import logging
from sqlalchemy.orm import Session
from datetime import datetime
import uuid
from typing import List, Dict

from sqlalchemy.dialects.postgresql import insert

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
    
def save_raw_conversation(
    db: Session,
    conversation_jid: str,
    messages: List[Dict[str, str | int]],
) -> int:
    """
    Persiste, de forma idempotente e em lote, as mensagens brutas de uma
    conversa de WhatsApp vindas da Evolution API.

    • Garante que `external_id` seja único no banco (cross‑conversation),
      usando `INSERT … ON CONFLICT DO NOTHING`.
    • Faz _upsert_ da Conversation para evitar SELECT extra.
    • Ignora mensagens sem `external_id` ou sem `timestamp`.
    • Retorna o nº de novas mensagens efetivamente inseridas.

    Parameters
    ----------
    db : Session
        Sessão SQLAlchemy aberta.
    conversation_jid : str
        Identificador do chat remoto (ex.: "551199999999@s.whatsapp.net").
    messages : list[dict]
        Payload no formato:
        {
            "external_id": str,
            "sender":      str,       # "Negociador" ou "Cliente"
            "text":        str,
            "timestamp":   int        # epoch segundos
        }

    Returns
    -------
    int
        Quantidade de mensagens novas adicionadas.
    """
    # ─────────────────────────────────────────────────────────────── conversation
    conversation = (
        db.query(models.Conversation)
        .filter_by(remote_jid=conversation_jid)
        .first()
    )
    if not conversation:
        conversation = models.Conversation(remote_jid=conversation_jid)
        db.add(conversation)
        db.flush()  # garante conversation.id

    # ─────────────────────────────────────────────────────────────── limpeza L1
    # ignora mensagens sem ID ou sem timestamp
    cleaned = [
        m
        for m in messages
        if m.get("external_id") and m.get("timestamp") is not None
    ]
    if not cleaned:
        return 0

    # dedup in‑memory no lote atual
    seen_batch: set[str] = set()
    rows: list[dict] = []
    for m in cleaned:
        ext_id = m["external_id"]
        if ext_id in seen_batch:
            continue
        seen_batch.add(ext_id)

        rows.append(
            dict(
                id=str(uuid.uuid4()),
                external_id=ext_id,
                conversation_id=conversation.id,
                sender=m["sender"],
                text=m["text"],
                message_timestamp=datetime.fromtimestamp(int(m["timestamp"])),
            )
        )
    if not rows:
        return 0

    # ────────────────────────────────────────────────────── bulk insert / upsert
    stmt = (
        insert(models.Message)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["external_id"])
    )

    try:
        result = db.execute(stmt)
        db.commit()
        inserted = result.rowcount or 0
        logger.debug(
            "save_raw_conversation • %s novas mensagens inseridas para %s",
            inserted,
            conversation_jid,
        )
        return inserted
    except Exception:
        db.rollback()
        logger.exception(
            "Erro ao salvar mensagens da conversa %s • rollback efetuado",
            conversation_jid,
        )
        return 0

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
    Usa o modelo de análise polimórfico e inclui todos os novos campos.
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

    analysis.extracted_data = analysis_data.get("extracted_data")
    analysis.temperature_assessment = analysis_data.get("temperature_analysis")
    analysis.director_decision = analysis_data.get("director_decision")
    
    analysis.kpis = analysis_data.get("kpis")
    analysis.advisor_recommendation = analysis_data.get("advisor_recommendation")
    analysis.context = analysis_data.get("context")
    analysis.formal_summary = analysis_data.get("formal_summary")
    
    logger.info(f"Análise completa (com sumário, KPIs, etc.) foi salva para a thread {conversation_id}.")
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