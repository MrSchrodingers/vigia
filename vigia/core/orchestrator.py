from datetime import datetime
import logging
import json
import asyncio
from typing import Tuple
from sqlalchemy.orm import Session

# Imports relativos para funcionar dentro do pacote
from db.session import SessionLocal
from ..services import database_service
from ..agents.specialist_agents import cautious_agent, inquisitive_agent
from ..agents.manager_agent import manager_agent
from ..agents.sentiment_agents import lexical_sentiment_agent, behavioral_sentiment_agent, sentiment_manager_agent
from ..agents.guard_agent import guard_agent
from ..agents.director_agent import director_agent

def fetch_history_and_date_from_db(db: Session, conversation_jid: str) -> Tuple[str, datetime]:
    """
    Busca o histórico e a data da ÚLTIMA mensagem de uma conversa no banco.
    """
    logging.info(f"Buscando histórico e data do DB para: {conversation_jid}")
    messages = (
        db.query(database_service.models.Message)
        .join(database_service.models.Conversation)
        .filter(database_service.models.Conversation.remote_jid == conversation_jid)
        .order_by(database_service.models.Message.message_timestamp.asc())
        .all()
    )
    if not messages: 
        return "", None
    
    # Formata o histórico completo
    history_text = "\n".join([f"{msg.sender}: {msg.text}" for msg in messages])
    # Pega o timestamp da última mensagem
    last_message_date = messages[-1].message_timestamp
    
    return history_text, last_message_date

async def run_extraction_department(history: str, reference_date: str) -> str:
    """Executa o pipeline do departamento de extração de forma assíncrona."""
    logging.info("--- DEPARTAMENTO (async): Extração de Dados ---")
    
    specialist_results = await asyncio.gather(
        cautious_agent.execute(history, reference_date),
        inquisitive_agent.execute(history, reference_date)
    )
    logging.info("Relatórios dos Especialistas de Extração concluídos.")
    
    final_report = await manager_agent.execute(specialist_results, history, reference_date)
    return final_report

async def run_temperature_department(history: str) -> str:
    """Executa o pipeline do departamento de temperatura de forma assíncrona."""
    logging.info("--- DEPARTAMENTO (async): Análise de Temperatura ---")
    specialist_results = await asyncio.gather(
        lexical_sentiment_agent.execute(history),
        behavioral_sentiment_agent.execute(history)
    )
    logging.info("Relatórios dos Especialistas de Sentimento concluídos.")
    final_report = await sentiment_manager_agent.execute(specialist_results[0], specialist_results[1])
    return final_report

async def run_multi_agent_cycle_async(payload: dict):
    """O ciclo de orquestração principal, assíncrono e focado em análise."""
    logging.info("Iniciando ciclo de ANÁLISE (async)...")
    
    conversation_id = payload.get("conversation_id")
    if not conversation_id:
        logging.error("Payload para análise inválido, faltando 'conversation_id'.")
        return

    # Passo 1: Obter Histórico do Banco de Dados (Operação Síncrona)
    db = SessionLocal()
    try:
        history_text, last_message_date = fetch_history_and_date_from_db(db, conversation_id)
        if not history_text:
            logging.warning(f"Não foi possível encontrar histórico para {conversation_id} no banco.")
            return
    finally:
        db.close()

    logging.info(f"Analisando conversa para {conversation_id}...")
    
    reference_date_str = last_message_date.strftime("%Y-%m-%d")
    logging.info(f"Analisando conversa para {conversation_id} com data de referência: {reference_date_str}")
    
    # Passo 2: Execução Paralela dos Departamentos
    department_reports = await asyncio.gather(
        run_extraction_department(history_text, reference_date_str),
        run_temperature_department(history_text)
    )
    final_data_str = department_reports[0]
    final_temp_str = department_reports[1]
    logging.info(f"Relatório Final de Extração: {final_data_str}")
    logging.info(f"Relatório Final de Temperatura: {final_temp_str}")

    # Passo 3: Meta-Análise e Decisão Final (Sequencial)
    logging.info("--- DEPARTAMENTO (async): Qualidade e Conformidade ---")
    guard_report_str = await guard_agent.execute(manager_agent.system_prompt, final_data_str)
    logging.info(f"Relatório do Guardião: {guard_report_str}")
    
    logging.info("--- DEPARTAMENTO (async): Diretoria ---")
    executive_summary = f"""
    Resumo da Negociação {conversation_id}:
    - Relatório de Dados Extraídos: {final_data_str}
    - Relatório de Temperatura da Conversa: {final_temp_str}
    """
    director_decision_str = await director_agent.execute(executive_summary)
    logging.info(f"Decisão Final do Diretor: {director_decision_str}")
    
    # Passo 4: Persistência da Análise no Banco de Dados (Operação Síncrona)
    logging.info("--- Fase de Persistência ---")
    full_report = None
    try:
        extracted_data = json.loads(final_data_str)
        temp_assessment = json.loads(final_temp_str)
        director_decision = json.loads(director_decision_str)
        
        full_report = {
            "extracao_dados": extracted_data,
            "analise_temperatura": temp_assessment,
            "decisao_diretor": director_decision,
        }

        db = SessionLocal()
        try:
            database_service.save_analysis_results(
                db=db,
                conversation_jid=conversation_id,
                messages=[],
                extracted_data=extracted_data,
                temp_assessment=temp_assessment,
                director_decision=director_decision
            )
            logging.info(f"Análise da conversa {conversation_id} foi salva/atualizada no banco.")
        finally:
            db.close()
    except (json.JSONDecodeError, TypeError) as e:
        logging.error(f"Erro ao decodificar JSON final de um dos agentes: {e}", exc_info=False)
        return None
    except Exception as e:
        logging.error(f"Erro inesperado ao salvar análise no banco: {e}", exc_info=True)
        return None

    logging.info(f"Ciclo assíncrono para a conversa {conversation_id} finalizado.")
    return full_report