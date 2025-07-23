import argparse
import logging
import json
import asyncio # Importa a biblioteca asyncio
from sqlalchemy.orm import Session
from typing import Tuple
from datetime import datetime

from db.session import SessionLocal
from db import models
from vigia.agents.specialist_agents import cautious_agent, inquisitive_agent
from vigia.agents.manager_agent import manager_agent
from vigia.agents.sentiment_agents import lexical_sentiment_agent, behavioral_sentiment_agent, sentiment_manager_agent
from vigia.agents.guard_agent import guard_agent
from vigia.agents.director_agent import director_agent
from vigia.services import database_service

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_history_and_date_from_db(db: Session, conversation_jid: str) -> Tuple[str, datetime]:
    """Busca o histórico e a data da ÚLTIMA mensagem de uma conversa no banco."""
    logging.info(f"Buscando histórico do DB para: {conversation_jid}")
    messages = (
        db.query(models.Message).join(models.Conversation)
        .filter(models.Conversation.remote_jid == conversation_jid)
        .order_by(models.Message.message_timestamp.asc()).all()
    )
    if not messages: 
        return "", None
    history_text = "\n".join([f"{msg.sender}: {msg.text}" for msg in messages])
    last_message_date = messages[-1].message_timestamp
    return history_text, last_message_date

# CORRIGIDO: A função principal agora é assíncrona
async def main_async():
    parser = argparse.ArgumentParser(description="Reanalisa uma conversa do banco de dados.")
    parser.add_argument("--conversa", required=True, help="O ID da conversa (remoteJid)")
    parser.add_argument("--salvar", action="store_true", help="Salva o resultado da análise no banco de dados.")
    args = parser.parse_args()

    db: Session = SessionLocal()
    try:
        history_text, last_message_date = fetch_history_and_date_from_db(db, args.conversa)
        if not history_text or not last_message_date:
            return

        reference_date_str = last_message_date.strftime("%Y-%m-%d")
        
        print("\n--- Histórico da Conversa (do Banco de Dados) ---")
        print(f"--- Data de Referência: {reference_date_str} ---")
        print(history_text)
        print("-------------------------------------------------\n")

        # ===================================================================
        # REPLICANDO O FLUXO ASSÍNCRONO COMPLETO DO ORQUESTRADOR
        # ===================================================================

        # Dispara os dois departamentos em paralelo
        department_reports = await asyncio.gather(
            run_extraction_department_local(history_text, reference_date_str),
            run_temperature_department_local(history_text)
        )
        final_data_str = department_reports[0]
        final_temp_str = department_reports[1]
        
        logging.info("--- DEPARTAMENTO: Qualidade e Conformidade ---")
        guard_report_str = await guard_agent.execute(manager_agent.system_prompt, final_data_str)
        logging.info(f"Relatório do Guardião: {guard_report_str}")
        
        logging.info("--- DEPARTAMENTO: Diretoria ---")
        executive_summary = f"""
        Resumo da Negociação {args.conversa} (analisada em {reference_date_str}):
        - Relatório de Dados Extraídos: {final_data_str}
        - Relatório de Temperatura da Conversa: {final_temp_str}
        """
        director_decision_str = await director_agent.execute(executive_summary)
        logging.info(f"Decisão Final do Diretor: {director_decision_str}")
        
        # Monta o relatório final
        full_report = {
            "extracao_dados": json.loads(final_data_str),
            "analise_temperatura": json.loads(final_temp_str),
            "auditoria_guardiao": json.loads(guard_report_str),
            "decisao_diretor": json.loads(director_decision_str)
        }
        
        print("\n--- RELATÓRIO DE REANÁLISE COMPLETO ---")
        print(json.dumps(full_report, indent=2, ensure_ascii=False))
        print("-----------------------------------------\n")

        if args.salvar:
                logging.info("Flag --salvar detectada. Salvando análise no banco de dados...")
                database_service.save_analysis_results(
                    db=db,
                    conversation_jid=args.conversa,
                    messages=[], # Não passamos mensagens, apenas a análise
                    extracted_data=full_report["extracao_dados"],
                    temp_assessment=full_report["analise_temperatura"],
                    director_decision=full_report["decisao_diretor"]
                )
                logging.info("Análise salva com sucesso!")
    finally:
        db.close()

async def run_extraction_department_local(history: str, reference_date: str) -> str:
    logging.info("--- DEPARTAMENTO: Extração de Dados ---")
    specialist_results = await asyncio.gather(
        cautious_agent.execute(history, reference_date),
        inquisitive_agent.execute(history, reference_date)
    )
    final_report = await manager_agent.execute(specialist_results, history, reference_date)
    logging.info(f"Relatório de Extração: {final_report}")
    return final_report

async def run_temperature_department_local(history: str) -> str:
    logging.info("--- DEPARTAMENTO: Análise de Temperatura ---")
    specialist_results = await asyncio.gather(
        lexical_sentiment_agent.execute(history),
        behavioral_sentiment_agent.execute(history)
    )
    final_report = await sentiment_manager_agent.execute(specialist_results[0], specialist_results[1])
    logging.info(f"Relatório de Temperatura: {final_report}")
    return final_report

if __name__ == "__main__":
    asyncio.run(main_async())