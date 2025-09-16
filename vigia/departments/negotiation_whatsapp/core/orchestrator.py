import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from db import models
from db.session import SessionLocal
from vigia.services import database_service, llm_service, pipedrive_service
from vigia.services.pipedrive_service import whatsapp_client

from ..agents import context_agent, specialist_agents
from ..agents.audio_agent import audio_tot_agent
from ..agents.director_agent import director_agent
from ..agents.guard_agent import guard_agent
from ..agents.manager_agent import manager_agent
from ..agents.sentiment_agents import (
    behavioral_sentiment_agent,
    lexical_sentiment_agent,
    sentiment_manager_agent,
)

logger = logging.getLogger(__name__)

AUDIO_RE = re.compile(r":\s*\[ÁUDIO", re.I)


async def _preprocess_audio_segments(raw_history: str, reference_date: str) -> str:
    processed_lines = []

    for line in raw_history.splitlines():
        if AUDIO_RE.search(line):
            # ── separa remetente do payload ──────────────────────────────
            sender, _, payload = line.partition(":")  # "Cliente", "[ÁUDIO…"
            payload = payload.strip()

            # ── chama o agente TOT só com o payload ─────────────────────
            raw_result = await audio_tot_agent.execute(payload, reference_date)
            cleaned = llm_service._clean_llm_response(raw_result)

            try:
                info = json.loads(cleaned)
            except json.JSONDecodeError:
                logging.error(f"AudioTOTAgent JSON inválido: {cleaned}")
                processed_lines.append(line)
                continue

            tag = " (BAIXA CONFIANÇA)" if info.get("possui_baixa_confianca") else ""
            transcricao = info.get("transcricao_limpa", "")

            processed_lines.append(f"{sender}: [TRANSCRIÇÃO ÁUDIO{tag}]: {transcricao}")
        else:
            processed_lines.append(line)

    return "\n".join(processed_lines)


async def _run_guarded_specialist(
    specialist_agent, history_with_context: str, reference_date: str
) -> dict:
    """
    Função auxiliar que executa um agente especialista e imediatamente valida sua saída.
    """
    # 1. Executa o agente especialista para obter o relatório JSON como string
    raw_output_str = await specialist_agent.execute(
        history_with_context, reference_date
    )

    # 2. Chama o PromptGuardAgent para validar a saída
    compliance_report_str = await guard_agent.execute(
        original_prompt=specialist_agent.system_prompt, agent_output=raw_output_str
    )
    compliance_report = json.loads(compliance_report_str)

    # 3. Verifica o resultado da validação
    if compliance_report.get("compliance_status") == "FALHA":
        logging.error(
            f"Falha de conformidade para o agente {type(specialist_agent).__name__}: {compliance_report.get('detalhes')}"
        )
        # Retorna um objeto vazio ou lança um erro para indicar a falha
        return {}

    # 4. Se passou na validação, retorna o JSON decodificado e limpo
    try:
        # Re-usa a função de limpeza que já tínhamos para garantir que é um JSON puro
        cleaned_json_str = llm_service._clean_llm_response(raw_output_str)
        return json.loads(cleaned_json_str)
    except json.JSONDecodeError:
        logging.error(
            f"Mesmo passando na conformidade, a saída do agente {type(specialist_agent).__name__} não é um JSON válido: {raw_output_str}"
        )
        return {}


def fetch_history_and_date_from_db(
    db: Session, conversation_jid: str
) -> Tuple[str, datetime]:
    """Busca o histórico e a data da ÚLTIMA mensagem de uma conversa no banco."""
    logging.info(f"Buscando histórico e data do DB para: {conversation_jid}")
    messages = (
        db.query(models.WhatsappMessage)
        .join(models.WhatsappConversation)
        .filter(models.WhatsappConversation.remote_jid == conversation_jid)
        .order_by(models.WhatsappMessage.message_timestamp.asc())
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


async def run_extraction_department(
    history_with_context: str, reference_date: str
) -> str:
    """
    Executa o sub-pipeline de extração de fatos com validação embutida.
    """
    logging.info("--- Sub-departamento: Extração de Fatos (WhatsApp) ---")

    # Executa os dois especialistas em paralelo, já com a validação do Guard
    specialist_reports_json = await asyncio.gather(
        _run_guarded_specialist(
            specialist_agents.cautious_agent, history_with_context, reference_date
        ),
        _run_guarded_specialist(
            specialist_agents.inquisitive_agent, history_with_context, reference_date
        ),
    )

    # O manager_agent agora recebe os relatórios já validados e em formato de objeto Python
    final_report_str = await manager_agent.execute(
        extraction_results=[
            json.dumps(report, ensure_ascii=False) for report in specialist_reports_json
        ],
        conversation_history=history_with_context,
        current_date=reference_date,
    )
    return final_report_str


async def run_temperature_department(history: str) -> str:
    """Executa o sub-pipeline de análise de temperatura."""
    logging.info("--- Sub-departamento: Análise de Temperatura (WhatsApp) ---")
    specialist_results = await asyncio.gather(
        lexical_sentiment_agent.execute(history),
        behavioral_sentiment_agent.execute(history),
    )
    return await sentiment_manager_agent.execute(
        specialist_results[0], specialist_results[1]
    )


async def execute_tool_call(tool_call: dict) -> Dict[str, Any]:
    """Executa uma chamada de ferramenta solicitada pelo Agente Diretor."""
    tool_name = tool_call.get("name")
    tool_args = tool_call.get("args", {})

    if tool_name and tool_name.lower() == "criaratividadenopipedrive":
        logging.info(f"Executando ferramenta: {tool_name} com args: {tool_args}")
        telefone = tool_args.get("person_phone")
        if not telefone:
            return {
                "status": "falha",
                "detalhe": "O telefone do contato não foi fornecido pela IA.",
            }

        person_data = await pipedrive_service.find_person_by_phone(
            whatsapp_client, telefone
        )
        if not person_data or not person_data.get("id"):
            return {
                "status": "falha",
                "detalhe": "Contato não encontrado no Pipedrive.",
            }

        person_id = person_data["id"]

        deal_data = await pipedrive_service.find_deals_by_person_id(
            whatsapp_client, person_id
        )
        logging.info(f"deal_data encontrado para criação de atividade: {deal_data}")
        deal_id = deal_data["id"] if deal_data else None

        result = await pipedrive_service.create_activity(
            client=whatsapp_client,
            person_id=person_id,
            deal_id=deal_id,
            due_date=tool_args.get("due_date"),
            note_summary=tool_args.get("note"),
            subject=tool_args.get("subject"),
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
    save_result = payload.get("save_result", True)  # Salva por padrão
    logging.info(
        f"PIPELINE WHATSAPP: Iniciando ciclo de análise para: {conversation_jid}"
    )

    db = SessionLocal()
    try:
        history_text, last_message_date = fetch_history_and_date_from_db(
            db, conversation_jid
        )
        if not history_text:
            logging.warning(
                f"Não foi possível encontrar histórico para {conversation_jid} no banco."
            )
            return None
    finally:
        db.close()

    reference_date_str = (
        last_message_date.strftime("%Y-%m-%d")
        if last_message_date
        else datetime.now().strftime("%Y-%m-%d")
    )

    # FASE 1: Contextualização
    history_text = await _preprocess_audio_segments(history_text, reference_date_str)
    enriched_context = await run_context_department(conversation_jid)
    history_with_context = (
        f"{enriched_context}\n\n---\n\nHISTÓRICO DA CONVERSA ORIGINAL:\n{history_text}"
    )

    # FASE 2: Execução Paralela
    department_reports = await asyncio.gather(
        run_extraction_department(history_with_context, reference_date_str),
        run_temperature_department(history_text),
    )
    final_data_str, final_temp_str = department_reports

    # FASE 3: Meta-Análise e Decisão Final
    guard_report_str = await guard_agent.execute(
        guard_agent.system_prompt, final_data_str
    )
    director_output_str = await director_agent.execute(
        final_data_str, final_temp_str, conversation_jid
    )

    director_decision = {}
    try:
        # Verifica se a saída já é um dicionário (caso de chamada de função)
        if isinstance(director_output_str, dict):
            director_output = director_output_str
        else:
            # Se for uma string, tenta decodificar como JSON
            director_output = json.loads(director_output_str)

        if (
            isinstance(director_output, dict)
            and director_output.get("type") == "function_call"
        ):
            # tool_result = await execute_tool_call(director_output)
            director_decision = {
                "acao_executada": director_output,
                "resultado_execucao": "tool_result",
            }
        else:
            director_decision = {"decisao_estrategica": director_output}
    except (json.JSONDecodeError, TypeError) as e:
        logging.error(f"Não foi possível decodificar a decisão do diretor: {e}")
        director_decision = {
            "erro": "Decisão do diretor mal formatada",
            "conteudo": director_output_str,
        }

    # FASE 4: Montagem e Persistência do Relatório Final
    try:
        full_report = {
            "analysis_metadata": {"conversation_jid": conversation_jid},
            "extracted_data": json.loads(final_data_str),
            "temperature_analysis": json.loads(final_temp_str),
            "guard_report": json.loads(guard_report_str),
            "director_decision": director_decision,
            "context": {"crm_context": enriched_context},
        }
    except json.JSONDecodeError:
        logging.error(
            "Erro ao montar o relatório final. Algum sub-relatório não é um JSON válido."
        )
        return None

    if save_result:
        db = SessionLocal()
        try:
            database_service.save_whatsapp_analysis_results(
                db=db, conversation_jid=conversation_jid, analysis_data=full_report
            )
            logging.info(
                f"Análise da conversa {conversation_jid} foi salva/atualizada no banco."
            )
        finally:
            db.close()

    logging.info(
        f"PIPELINE WHATSAPP: Ciclo para a conversa {conversation_jid} finalizado."
    )
    return full_report
