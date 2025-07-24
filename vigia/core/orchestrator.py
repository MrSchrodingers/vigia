from datetime import datetime
import logging
import json
import asyncio
from typing import Tuple
from sqlalchemy.orm import Session

from db.session import SessionLocal
from vigia.services import pipedrive_service
from ..services import database_service
from ..agents.manager_agent import manager_agent
from ..agents.sentiment_agents import lexical_sentiment_agent, behavioral_sentiment_agent, sentiment_manager_agent
from ..agents.guard_agent import guard_agent
from ..agents.director_agent import director_agent
from vigia.agents import context_agent, specialist_agents

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

async def run_context_department(conversation_jid: str) -> str:
    """
    Executa o departamento de contexto (estratégia GAN).
    1. Minerador de Dados (Gerador) busca dados brutos.
    2. Sintetizador (Validador) cria um resumo de contexto.
    """
    logging.info("--- DEPARTAMENTO (async): Contexto ---")
    raw_pipedrive_data = await context_agent.data_miner_agent.execute(conversation_jid)
    context_summary = await context_agent.context_synthesizer_agent.execute(raw_pipedrive_data)
    return context_summary

async def run_extraction_department(history_with_context: str, reference_date: str) -> str:
    """
    Executa o pipeline do departamento de extração (estratégia ToT)
    usando um histórico já enriquecido com contexto.
    """
    logging.info("--- DEPARTAMENTO (async): Extração de Fatos ---")
    
    # Geradores de "Pensamentos"
    specialist_reports = await asyncio.gather(
        specialist_agents.cautious_agent.execute(history_with_context, reference_date),
        specialist_agents.inquisitive_agent.execute(history_with_context, reference_date)
    )
    logging.info("Relatórios dos Especialistas de Extração (Pensamentos) concluídos.")
    
    # Sintetizador de "Pensamentos"
    final_report = await manager_agent.execute(specialist_reports, history_with_context, reference_date)
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

async def execute_tool_call(tool_call: dict):
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {})
    
    if tool_name and tool_name.lower() == "criaratividadenopipedrive": 
        logging.info(f"Executando ferramenta: {tool_name} com args: {tool_args}")
        
        telefone = tool_args.get("person_phone") 
        if not telefone:
            return {"status": "falha", "detalhe": "O telefone do contato não foi fornecido pela IA."}
            
        person_data = await pipedrive_service.find_person_by_phone(telefone)
        
        if not person_data or not person_data.get("id"):
            logging.warning(f"Pessoa com telefone {telefone} não encontrada no Pipedrive. A atividade não será criada.")
            return {"status": "falha", "detalhe": "Contato não encontrado no Pipedrive."}

        person_id = person_data["id"]
        result = await pipedrive_service.create_activity(
            person_id=person_id,
            due_date=tool_args.get("due_date"),          
            note_summary=tool_args.get("note"),       
            subject=tool_args.get("subject")            
        )
        return {"status": "sucesso", "resultado_pipedrive": result}
        
    elif tool_name and tool_name.lower() == "alertar_supervisor":
        logging.warning(f"ALERTA DE SUPERVISOR: {tool_args.get('motivo')}")
        return {"status": "sucesso", "detalhe": "Supervisor alertado."}
        
    else:
        logging.error(f"Tentativa de chamar uma ferramenta desconhecida: {tool_name}")
        return {"status": "erro", "detalhe": "Ferramenta não encontrada."}
    
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
    
    # FASE 1: Contextualização (GAN)
    enriched_context = await run_context_department(conversation_id)
    
    # Combina o contexto com o histórico para as próximas fases
    full_history = f"{enriched_context}\n\n---\n\nHISTÓRICO DA CONVERSA ORIGINAL:\n{history_text}"

    # FASE 2: Execução Paralela dos Departamentos de Extração e Temperatura
    department_reports = await asyncio.gather(
        run_extraction_department(full_history, reference_date_str), 
        run_temperature_department(history_text)
    )
    final_data_str = department_reports[0]
    final_temp_str = department_reports[1]
    
    # Convertendo para dict aqui para passar ao Diretor
    final_data_dict = json.loads(final_data_str)
    final_data_dict['conversation_id'] = conversation_id
    
    logging.info(f"Relatório Final de Extração: {final_data_str}")
    logging.info(f"Relatório Final de Temperatura: {final_temp_str}")

    # Passo 3: Meta-Análise e Decisão Final (Sequencial)
    logging.info("--- DEPARTAMENTO (async): Qualidade e Conformidade ---")
    guard_report_str = await guard_agent.execute(guard_agent.system_prompt, final_data_str)
    logging.info(f"Relatório do Guardião: {guard_report_str}")
    
    logging.info("--- DEPARTAMENTO (async): Diretoria ---")
    executive_summary = f"""
    Resumo da Negociação {conversation_id}:
    - Relatório de Dados Extraídos: {final_data_str}
    - Relatório de Temperatura da Conversa: {final_temp_str}
    """
    director_output = await director_agent.execute(executive_summary, final_data_dict)
    director_decision = {}
    # Passo 3.5: Execução da Ferramenta, se solicitada
    if isinstance(director_output, dict) and director_output.get("type") == "function_call":
        tool_result = await execute_tool_call(director_output)
        director_decision = {
            "acao_executada": director_output.get("name"),
            "parametros": director_output.get("args"),
            "resultado_execucao": tool_result
        }
        logging.info(f"Decisão Final do Diretor (via ferramenta): {director_decision}")
    else:
        director_decision = json.loads(director_output)
        logging.info(f"Decisão Final do Diretor (estratégica): {director_decision}")
        
    # Passo 4: Persistência da Análise no Banco de Dados (Operação Síncrona)
    logging.info("--- Fase de Persistência ---")
    try:
        extracted_data = json.loads(final_data_str)
        temp_assessment = json.loads(final_temp_str)
        
        if not isinstance(director_decision, dict):
             raise TypeError(f"A decisão do diretor não é um dicionário válido para salvar: {director_decision}")

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
        logging.error(f"Erro ao processar JSON para persistência: {e}", exc_info=False)
        return None
    except Exception as e:
        logging.error(f"Erro inesperado ao salvar análise no banco: {e}", exc_info=True)
        return None

    logging.info(f"Ciclo assíncrono para a conversa {conversation_id} finalizado.")
    return full_report