from datetime import datetime
import logging
import json
import asyncio
from typing import Tuple, Dict, Any, Optional
from sqlalchemy.orm import Session

from db.session import SessionLocal
from db import models
from vigia.services import pipedrive_service
from vigia.services.pipedrive_service import whatsapp_client
from vigia.services import database_service
from ..agents.manager_agent import manager_agent
from ..agents.sentiment_agents import lexical_sentiment_agent, behavioral_sentiment_agent, sentiment_manager_agent
from ..agents.guard_agent import guard_agent
from ..agents.director_agent import director_agent
from ..agents import context_agent, specialist_agents

logger = logging.getLogger(__name__)

def fetch_history_and_date_from_db(db: Session, conversation_jid: str) -> Tuple[str, datetime]:
    """Busca o histórico e a data da ÚLTIMA mensagem de uma conversa no banco."""
    logging.info(f"Buscando histórico e data do DB para: {conversation_jid}")
    messages = (
        db.query(models.Message)
        .join(models.Conversation)
        .filter(models.Conversation.remote_jid == conversation_jid)
        .order_by(models.Message.message_timestamp.asc())
        .all()
    )
    if not messages: 
        return "", None
    
    history_text = "\n".join([f"{msg.sender}: {msg.text}" for msg in messages])
    last_message_date = messages[-1].message_timestamp
    return history_text, last_message_date

async def run_context_department(conversation_jid: str) -> str:
    """Executa o sub-pipeline de contexto."""
    logging.info("--- Sub-departamento: Contexto (WhatsApp) ---")
    raw_pipedrive_data = await context_agent.data_miner_agent.execute(conversation_jid)
    return await context_agent.context_synthesizer_agent.execute(raw_pipedrive_data)

async def run_extraction_department(history_with_context: str, reference_date: str) -> str:
    """Executa o sub-pipeline de extração de fatos."""
    logging.info("--- Sub-departamento: Extração de Fatos (WhatsApp) ---")
    specialist_reports = await asyncio.gather(
        specialist_agents.cautious_agent.execute(history_with_context, reference_date),
        specialist_agents.inquisitive_agent.execute(history_with_context, reference_date)
    )
    return await manager_agent.execute(specialist_reports, history_with_context, reference_date)

async def run_temperature_department(history: str) -> str:
    """Executa o sub-pipeline de análise de temperatura."""
    logging.info("--- Sub-departamento: Análise de Temperatura (WhatsApp) ---")
    specialist_results = await asyncio.gather(
        lexical_sentiment_agent.execute(history),
        behavioral_sentiment_agent.execute(history)
    )
    return await sentiment_manager_agent.execute(specialist_results[0], specialist_results[1])

async def execute_tool_call(tool_call: dict) -> Dict[str, Any]:
    """Executa uma chamada de ferramenta solicitada pelo Agente Diretor."""
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {})
    
    if tool_name and tool_name.lower() == "criaratividadenopipedrive": 
        logging.info(f"Executando ferramenta: {tool_name} com args: {tool_args}")
        telefone = tool_args.get("person_phone") 
        if not telefone:
            return {"status": "falha", "detalhe": "O telefone do contato não foi fornecido pela IA."}
            
        person_data = await pipedrive_service.find_person_by_phone(whatsapp_client, telefone)
        if not person_data or not person_data.get("id"):
            return {"status": "falha", "detalhe": "Contato não encontrado no Pipedrive."}

        person_id = person_data["id"]
        person_name = person_data["name"]
        
        deal_data = await pipedrive_service.find_deal_by_person_name(whatsapp_client, person_name)
        deal_id = deal_data["id"] if deal_data else None
        
        result = await pipedrive_service.create_activity(
            client=whatsapp_client,
            person_id=person_id,
            deal_id=deal_id,
            due_date=tool_args.get("due_date"),
            note_summary=tool_args.get("note"),
            subject=tool_args.get("subject")
        )
        return {"status": "sucesso", "resultado_pipedrive": result}
        
    elif tool_name and tool_name.lower() == "alertarsupervisor":
        logging.warning(f"ALERTA DE SUPERVISOR: {tool_args.get('motivo')}")
        return {"status": "sucesso", "detalhe": "Supervisor alertado."}
        
    else:
        logging.error(f"Tentativa de chamar uma ferramenta desconhecida: {tool_name}")
        return {"status": "erro", "detalhe": "Ferramenta não encontrada."}
    
async def run_department_pipeline(payload: dict) -> Optional[Dict[str, Any]]:
    """O Diretor-Setorial do WhatsApp. Executa o ciclo completo de análise."""
    conversation_jid = payload.get("conversation_id")
    save_result = payload.get("save_result", True) # Salva por padrão
    logging.info(f"PIPELINE WHATSAPP: Iniciando ciclo de análise para: {conversation_jid}")
    
    db = SessionLocal()
    try:
        history_text, last_message_date = fetch_history_and_date_from_db(db, conversation_jid)
        if not history_text:
            logging.warning(f"Não foi possível encontrar histórico para {conversation_jid} no banco.")
            return None
    finally:
        db.close()

    reference_date_str = last_message_date.strftime("%Y-%m-%d") if last_message_date else datetime.now().strftime("%Y-%m-%d")
    
    # FASE 1: Contextualização
    enriched_context = await run_context_department(conversation_jid)
    history_with_context = f"{enriched_context}\n\n---\n\nHISTÓRICO DA CONVERSA ORIGINAL:\n{history_text}"

    # FASE 2: Execução Paralela
    department_reports = await asyncio.gather(
        run_extraction_department(history_with_context, reference_date_str), 
        run_temperature_department(history_text)
    )
    final_data_str, final_temp_str = department_reports

    # FASE 3: Meta-Análise e Decisão Final
    guard_report_str = await guard_agent.execute(guard_agent.system_prompt, final_data_str)
    director_output_str = await director_agent.execute(final_data_str, final_temp_str, conversation_jid)
    
    director_decision = {}
    try:
        director_output = json.loads(director_output_str)
        if isinstance(director_output, dict) and director_output.get("type") == "function_call":
            tool_result = await execute_tool_call(director_output)
            director_decision = {"acao_executada": director_output, "resultado_execucao": tool_result}
        else:
             director_decision = {"decisao_estrategica": director_output}
    except (json.JSONDecodeError, TypeError) as e:
        logging.error(f"Não foi possível decodificar a decisão do diretor: {e}")
        director_decision = {"erro": "Decisão do diretor mal formatada", "conteudo": director_output_str}

    # FASE 4: Montagem e Persistência do Relatório Final
    try:
        full_report = {
            "analysis_metadata": {"conversation_jid": conversation_jid},
            "extracted_data": json.loads(final_data_str),
            "temperature_analysis": json.loads(final_temp_str),
            "guard_report": json.loads(guard_report_str),
            "director_decision": director_decision,
            "context": {"crm_context": enriched_context}
        }
    except json.JSONDecodeError:
        logging.error("Erro ao montar o relatório final. Algum sub-relatório não é um JSON válido.")
        return None

    if save_result:
        db = SessionLocal()
        try:
            database_service.save_whatsapp_analysis_results(db=db, conversation_jid=conversation_jid, analysis_data=full_report)
            logging.info(f"Análise da conversa {conversation_jid} foi salva/atualizada no banco.")
        finally:
            db.close()
    
    logging.info(f"PIPELINE WHATSAPP: Ciclo para a conversa {conversation_jid} finalizado.")
    return full_report