import logging
import asyncio
import json
from sqlalchemy.orm import Session
from db.session import SessionLocal
from db import models 
from vigia.services import database_service

# Importando as instâncias dos agentes do __init__.py
from ..agents import (
    context_miner_agent,
    context_synthesizer_agent,
    extraction_subject_agent,
    extraction_legal_financial_agent,
    extraction_stage_agent,
    extraction_manager_agent,
    temperature_behavioral_agent,
    director_agent,
)
# from .tools import execute_email_tool_call # Descomente quando a função de ferramentas estiver pronta

logger = logging.getLogger(__name__)

def get_thread_data_from_db(db: Session, conversation_id: str) -> (dict, str):
    """Busca os dados de uma thread e seu histórico de mensagens do banco."""
    thread = db.query(models.EmailThread).filter(models.EmailThread.conversation_id == conversation_id).first()
    if not thread:
        logger.error(f"Thread com conversation_id {conversation_id} não encontrada no banco.")
        return None, None

    messages = sorted(thread.messages, key=lambda m: m.sent_datetime)
    full_history_text = "\n\n".join(
        [f"De: {msg.sender}\nData: {msg.sent_datetime.strftime('%d/%m/%Y %H:%M')}\n\n{msg.body}" for msg in messages]
    )

    thread_metadata = {
        "participants": thread.participants,
        "subject": thread.subject,
        "first_email_date": thread.first_email_date.isoformat(),
        "last_email_date": thread.last_email_date.isoformat(),
        "total_messages": len(messages),
        "has_attachments": any(msg.has_attachments for msg in messages),
        "importance": [msg.importance for msg in messages if msg.importance]
    }
    return thread_metadata, full_history_text

async def run_extraction_department(subject: str, history_text: str) -> str:
    """Executa o sub-pipeline de extração de dados."""
    logger.info("--- Sub-departamento: Extração de Fatos (E-mail) ---")
    specialist_reports = await asyncio.gather(
        extraction_subject_agent.execute(subject),
        extraction_legal_financial_agent.execute(history_text),
        extraction_stage_agent.execute(history_text)
    )
    return await extraction_manager_agent.execute(*specialist_reports)

async def run_temperature_department(history_text: str, metadata: dict) -> str:
    """Executa o sub-pipeline de análise de temperatura."""
    logger.info("--- Sub-departamento: Análise de Temperatura (E-mail) ---")
    return await temperature_behavioral_agent.execute(metadata)

async def run_department_pipeline(payload: dict) -> dict:
    """O Diretor-Setorial de E-mail. Executa o ciclo completo de análise."""
    conversation_id = payload.get("conversation_id")
    save_result = payload.get("save_result", False)
    logger.info(f"PIPELINE E-MAIL: Iniciando análise para a thread: {conversation_id}")
    
    db = SessionLocal()
    try:
        thread_metadata, full_history_text = get_thread_data_from_db(db, conversation_id)
        if not thread_metadata:
            return None
    finally:
        db.close()

    # --- FASE 1: Contexto ---
    # CORREÇÃO: Passando apenas o 'subject' para o agente, como ele espera.
    raw_crm_data = await context_miner_agent.execute(thread_metadata['subject'])
    enriched_context = await context_synthesizer_agent.execute(raw_crm_data)
    history_with_context = f"{enriched_context}\n\n---\n\nHISTÓRICO DA THREAD:\n{full_history_text}"

    # --- FASE 2: Execução Paralela ---
    department_reports = await asyncio.gather(
        run_extraction_department(thread_metadata['subject'], history_with_context),
        run_temperature_department(full_history_text, thread_metadata)
    )
    final_data_str = department_reports[0]
    final_temp_str = department_reports[1]

    # --- FASE 3: Diretoria ---
    logger.info("--- DEPARTAMENTO: Diretoria (E-mail) ---")
    director_output_str = await director_agent.execute(final_data_str, final_temp_str, conversation_id)
    
    director_decision = {}
    try:
        director_output = json.loads(director_output_str)
        if 'acao' in director_output:
            logger.info(f"Diretor solicitou ação: {director_output['acao']['nome_ferramenta']}")
            # tool_result = await execute_email_tool_call(director_output['acao'])
            director_decision = {"acao_executada": director_output['acao'], "resultado_execucao": "simulado"}
        elif 'resumo_estrategico' in director_output:
            director_decision = {"resumo_estrategico": director_output['resumo_estrategico']}
    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Não foi possível decodificar a decisão do diretor: {e}")
        director_decision = {"erro": "Decisão do diretor mal formatada", "conteudo": director_output_str}

    # --- Montagem do relatório final ---
    full_report = {
        "analysis_metadata": {"conversation_id": conversation_id},
        "extracted_data": json.loads(final_data_str),
        "temperature_analysis": json.loads(final_temp_str),
        "director_decision": director_decision,
        "context": {"crm_context": enriched_context}
    }

    if save_result:
        logger.info(f"Salvando resultado da análise para a thread {conversation_id}")
        db = SessionLocal()
        try:
            database_service.save_email_analysis_results(db=db, analysis_data=full_report)
            pass
        finally:
            db.close()
    
    logger.info(f"PIPELINE E-MAIL: Análise da thread {conversation_id} finalizada.")
    return full_report