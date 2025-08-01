import logging
import asyncio
import json
import re
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, Union
from vigia.services import database_service, pipedrive_service
from vigia.services.pipedrive_service import email_client
from vigia.departments.negotiation_email.utils  import clean_html_body

from sqlalchemy.orm import Session
from db.session import SessionLocal
from db import models

# ==== Agents ================================================================
from ..agents import (
    context_miner_agent,
    context_synthesizer_agent,
    extraction_subject_agent,
    extraction_stage_agent,
    extraction_manager_agent,
    temperature_behavioral_agent,
    director_agent,
    judicial_negotiation_advisor_agent,
    formal_summarizer_agent,
    validator_agent,
    refiner_agent,
    extraction_legal_financial_agent 
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------------
async def execute_tool_call(
    tool_call: Dict[str, Any], 
    raw_crm: Dict[str, Any]
) -> Dict[str, Any]:
    """Executa a chamada de ferramenta solicitada pelo Diretor."""
    tool_name = tool_call.get("name")      
    tool_args = tool_call.get("args", {})
    
    person_id = raw_crm.get("person", {}).get("id")
    deal_info = raw_crm.get("deal", {})
    deal_id = deal_info.get("id")
    user_id = deal_info.get("user_id")
    
    if not person_id or not deal_id:
        msg = "Ação não pôde ser executada: ID da Pessoa ou do Negócio não encontrado no Pipedrive."
        logger.error(msg)
        return {"status": "falha", "detalhe": msg}

    if not user_id: 
        logger.warning(f"Não foi encontrado 'user_id' no deal {deal_id}. A atividade será criada sem um proprietário específico.")

    if tool_name == "AgendarFollowUp":
        logger.info(f"Executando ferramenta: {tool_name} com args: {tool_args}")
        result = await pipedrive_service.create_activity(
            client=email_client,
            person_id=person_id,
            deal_id=deal_id,
            user_id=user_id,
            due_date=tool_args.get("due_date"),
            note_summary=tool_args.get("note"),
            subject=tool_args.get("subject")
        )
        return {"status": "sucesso", "resultado_pipedrive": result}
        
    elif tool_name == "AlertarSupervisorParaAtualizacao":
        logger.warning(f"Executando ferramenta de alerta: {tool_name} com args: {tool_args}")
        
        urgencia = tool_args.get('urgencia', 'Média').upper()
        deal_title = deal_info.get('title', 'Negócio')
        
        assunto_contextual = tool_args.get("assunto_alerta")
        if assunto_contextual:
            subject = f"[{urgencia}] {assunto_contextual}: {deal_title}"
        else:
            subject = f"[{urgencia}] REVISAR/ATUALIZAR: {deal_title}"

        result = await pipedrive_service.create_activity(
            client=email_client,
            person_id=person_id,
            deal_id=deal_id,
            user_id=user_id,
            due_date=tool_args.get("due_date"),
            note_summary=tool_args.get("motivo"), 
            subject=subject 
        )
        return {"status": "sucesso", "resultado_pipedrive": result}

    else:
        logger.error(f"Tentativa de chamar uma ferramenta desconhecida: {tool_name}")
        return {"status": "erro", "detalhe": "Ferramenta não encontrada."}
    
def _format_summary_for_note(summary_data: Dict[str, Any]) -> str:
    """Formata o JSON do sumário em um texto HTML rico e legível para a nota do Pipedrive."""
    if not summary_data or "erro" in summary_data:
        return "<i>Erro ao gerar o sumário da análise.</i>"

    style = 'style="padding-bottom: 10px; margin-bottom: 10px; border-bottom: 1px solid #eee;"'
    
    html_parts = [f'<div {style}><h2>📝 Resumo da Análise da Negociação</h2></div>']

    # --- Seção: Resumo Executivo ---
    if summary_data.get("sumario_executivo"):
        html_parts.append(
            f"<div {style}>"
            f'<h4>Resumo Executivo</h4>'
            f'<p>{summary_data["sumario_executivo"]}</p>'
            f"</div>"
        )
    
    # --- Seção: Status ---
    status_info = summary_data.get("status_e_proximos_passos", {})
    if status_info.get("status_atual"):
         html_parts.append(
            f"<div {style}>"
            f'<h4>Status Atual</h4>'
            f'<p><strong>{status_info["status_atual"]}</strong></p>'
            f"</div>"
        )

    # --- Seção: Histórico da Negociação ---
    historico = summary_data.get("historico_negociacao", {})
    if historico:
        # Começa a seção de histórico
        hist_parts = [f'<div {style}><h4>Histórico da Negociação</h4>']
        
        # Adiciona o fluxo geral da negociação
        if historico.get("fluxo"):
            hist_parts.append(f'<p>{historico["fluxo"]}</p>')
        
        # Argumentos do Cliente
        cliente_args = historico.get("argumentos_cliente")
        if cliente_args:
            hist_parts.append('<strong>Argumentos do Cliente:</strong>')
            # Trata tanto se for uma lista quanto um texto simples
            if isinstance(cliente_args, list):
                hist_parts.append('<ul>')
                for arg in cliente_args:
                    hist_parts.append(f'<li>{arg}</li>')
                hist_parts.append('</ul>')
            else:
                hist_parts.append(f'<p><i>{cliente_args}</i></p>')

        # Argumentos Internos
        internos_args = historico.get("argumentos_internos")
        if internos_args:
            hist_parts.append('<br><strong>Nossos Argumentos:</strong>')
            if isinstance(internos_args, list):
                hist_parts.append('<ul>')
                for arg in internos_args:
                    hist_parts.append(f'<li>{arg}</li>')
                hist_parts.append('</ul>')
            else:
                hist_parts.append(f'<p><i>{internos_args}</i></p>')
        
        # Fecha a seção de histórico
        hist_parts.append('</div>')
        html_parts.append("".join(hist_parts))

    return "".join(html_parts)

def _safe_json_loads(text: Union[str, bytes, dict]) -> Dict[str, Any]:
    """
    Converte uma string JSON para um dicionário de forma segura.
    Se o input já for um dicionário, retorna-o diretamente.
    """
    # 1. Se o input já é um dicionário, não há nada a fazer. Retorne-o.
    if isinstance(text, dict):
        return text

    # 2. Se for bytes, decodifique para string.
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    
    # 3. Garante que temos uma string para trabalhar.
    if not isinstance(text, str):
        logger.error(f"Input para _safe_json_loads não é str, bytes ou dict, mas {type(text)}. Retornando dict vazio.")
        return {}

    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"```[a-zA-Z]*", "", clean).strip().rstrip("`").strip()
    
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logger.warning("JSON original inválido (%s). Tentando heurística de busca...", e)
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as e2:
                logger.error("Heurística de busca JSON falhou: %s", e2)
        
        raise e


def _seconds_between(start_iso: str, end_iso: str) -> int:
    try:
        return int((datetime.fromisoformat(end_iso) - datetime.fromisoformat(start_iso)).total_seconds())
    except Exception:
        return -1


def _score_aderencia_prompt(extracted_data: Dict[str, Any]) -> float:
    if not extracted_data:
        return 0.0
    total = len(extracted_data)
    filled = sum(1 for v in extracted_data.values() if v not in (None, "", [], {}))
    return round(filled / total, 2) if total else 0.0


def _build_kpis(thread_meta: Dict[str, Any], extracted_data: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tempo_resposta_seg": _seconds_between(thread_meta["first_email_date"], thread_meta["last_email_date"]),
        "delta_valor_oferta_%": -1,
        "prob_sucesso_modelo_ml": -1,
        "score_aderencia_prompt": _score_aderencia_prompt(extracted_data),
    }

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def get_thread_data_from_db(db: Session, conversation_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    thread = (
        db.query(models.EmailThread)
        .filter(models.EmailThread.conversation_id == conversation_id)
        .first()
    )
    if not thread:
        logger.error("Thread %s não encontrada", conversation_id)
        return None, None
    
    messages = sorted(thread.messages, key=lambda m: m.sent_datetime)
    
    history_parts = []
    for m in messages:
        cleaned_body = clean_html_body(m.body) 
        history_parts.append(
            f"De: {m.sender}\nData: {m.sent_datetime.strftime('%d/%m/%Y %H:%M')}\n\n{cleaned_body}"
        )
    
    history = "\n\n---\n\n".join(history_parts)
    
    meta = {
        "participants": thread.participants,
        "subject": thread.subject,
        "first_email_date": thread.first_email_date.isoformat(),
        "last_email_date": thread.last_email_date.isoformat(),
        "total_messages": len(messages),
        "has_attachments": any(m.has_attachments for m in messages),
        "importance": [m.importance for m in messages if m.importance],
    }
    return meta, history

# ---------------------------------------------------------------------------
# Sub-departamentos
# ---------------------------------------------------------------------------
async def run_adversarial_extraction(email_body: str) -> str:
    """
    Executa o fluxo de extração adversarial de 3 etapas para garantir máxima precisão.
    """
    logger.info("Iniciando extração adversarial (Etapa 1: Geração)...")
    # ETAPA 1: O Gerador faz a primeira tentativa
    initial_extraction = await extraction_legal_financial_agent.execute(email_body)
    logger.info("Geração inicial concluída. Iniciando Etapa 2: Validação...")

    # ETAPA 2: O Validador critica a primeira tentativa
    validation_report_str = await validator_agent.execute(
        email_body=email_body,
        json_extraction=initial_extraction
    )
    logger.info(f"Validação concluída. Relatório: {validation_report_str}")
    
    try:
        validation_report = _safe_json_loads(validation_report_str)
    except json.JSONDecodeError:
        logger.error("Falha ao decodificar o relatório de validação. Abortando refinamento.")
        return initial_extraction

    if validation_report.get("is_valid"):
        logger.info("Extração inicial validada com sucesso. Retornando resultado.")
        return initial_extraction

    logger.info("Validação encontrou pontos de melhoria. Iniciando Etapa 3: Refinamento...")
    # ETAPA 3: O Refinador dá a palavra final
    final_extraction = await refiner_agent.execute(
        email_body=email_body,
        initial_extraction=initial_extraction,
        validation_report=validation_report_str
    )
    logger.info("Refinamento concluído. Retornando extração final.")

    return final_extraction


async def run_temperature_department(history_txt: str, meta: Dict[str, Any]) -> str:
    logger.info("-- Analysing temperature & behaviour")
    return await temperature_behavioral_agent.execute(meta)

# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
async def run_department_pipeline(payload: Dict[str, Any]) -> Dict[str, Any]:
    conv_id = payload.get("conversation_id")
    save_result = payload.get("save_result", False)
    logger.info("PIPELINE EMAIL • Iniciando para %s", conv_id)

    db = SessionLocal()
    try:
        thread_meta, full_history = get_thread_data_from_db(db, conv_id)
        if not thread_meta:
            return {}
    finally:
        db.close()

    # 1) Contexto ============================================================
    raw_crm = await context_miner_agent.execute(thread_meta["subject"])
    enriched_ctx = await context_synthesizer_agent.execute(raw_crm)
    history_plus_ctx = f"{enriched_ctx}\n\n---\n\nHISTÓRICO:\n{full_history}"

    # 2) Paralelo: extração + temperatura ===================================
    logger.info("Iniciando extração de dados em paralelo (com processo adversarial)...")
    (
        subject_extraction_str,
        legal_financial_extraction_str,
        stage_extraction_str,
        temp_str
    ) = await asyncio.gather(
        extraction_subject_agent.execute(thread_meta["subject"]),
        run_adversarial_extraction(history_plus_ctx),
        extraction_stage_agent.execute(history_plus_ctx),
        run_temperature_department(full_history, thread_meta)
    )

    logger.info("Consolidando relatórios de extração...")
    extract_str = await extraction_manager_agent.execute(
        subject_extraction_str,
        legal_financial_extraction_str,
        stage_extraction_str
    )
    
    extract_data = _safe_json_loads(extract_str)
    temp_data = _safe_json_loads(temp_str)

    # 3) KPIs ===============================================================
    kpis = _build_kpis(thread_meta, extract_data)

     # 4) Diretoria ==========================================================
    logger.info("-- Solicitando decisão do Diretor Estratégico...")
    director_raw = await director_agent.execute(
        extraction_report=json.dumps(extract_data), 
        temperature_report=json.dumps(temp_data),
        crm_context=json.dumps(raw_crm),
        conversation_id=conv_id
    )
    
    director_decision = {}
    pipedrive_actions_results = [] 
    try:
        decision_json = _safe_json_loads(director_raw)
        
        actions_to_execute = decision_json.get("actions")
        tool_name_direct = decision_json.get("name")

        # CASO 1: Múltiplas ações na lista "actions"
        if actions_to_execute and isinstance(actions_to_execute, list):
            logger.info(f"Diretor solicitou {len(actions_to_execute)} ações (formato de lista).")
            for action_call in actions_to_execute:
                single_action_call = {
                    "name": action_call.get("tool_name"),
                    "args": action_call.get("tool_args")
                }
                logger.info(f"Executando ação: {single_action_call['name']}")
                execution_result = await execute_tool_call(single_action_call, raw_crm)
                pipedrive_actions_results.append({
                    "acao_executada": single_action_call,
                    "resultado_execucao": execution_result
                })
            director_decision = {"acoes_executadas": pipedrive_actions_results}

        # CASO 2: Ação única no formato de "function_call"
        elif tool_name_direct and decision_json.get("type") == "function_call":
            logger.info("Diretor solicitou 1 ação (formato de chamada de função direta).")
            single_action_call = {
                "name": tool_name_direct,
                "args": decision_json.get("args", {})
            }
            execution_result = await execute_tool_call(single_action_call, raw_crm)
            pipedrive_actions_results.append({
                "acao_executada": single_action_call,
                "resultado_execucao": execution_result
            })
            director_decision = {"acoes_executadas": pipedrive_actions_results}

        # CASO 3: Nenhuma ação, apenas resumo estratégico
        elif "resumo_estrategico" in decision_json:
            director_decision = {"resumo_estrategico": decision_json.get("resumo_estrategico", "N/A")}
        
        # CASO 4: Formato desconhecido
        else:
             logger.error("Decisão do Diretor em formato inesperado (nem 'actions' nem 'function_call' nem 'resumo_estrategico').")
             director_decision = {"erro": "Formato de decisão desconhecido", "raw_output": str(director_raw)}

    except (json.JSONDecodeError, TypeError) as e:
        logger.error(f"Não foi possível decodificar ou processar a decisão do diretor: {e}")
        director_decision = {"erro": "Decisão do diretor mal formatada", "raw_output": str(director_raw)}

    # 5) Advisor Judicial ===================================================
    advisor_payload = {
        "extract": extract_data,
        "temperature": temp_data,
        "kpis": kpis,
        "crm_context": enriched_ctx,
    }
    advisor_raw = await judicial_negotiation_advisor_agent.execute(advisor_payload)
    try:
        advisor_json = _safe_json_loads(advisor_raw)
    except json.JSONDecodeError:
        advisor_json = {"erro": "advisor output inválido", "raw": advisor_raw}
    
    # 6) Summarizator ===================================================
    logger.info("-- Gerando sumário formal")
    
    # Criamos um payload específico para o sumarizador, garantindo que ele receba os dados estruturados.
    summarizer_payload = {
        "dados_extraidos": extract_data,
        "analise_temperatura": temp_data,
        "contexto_crm": raw_crm
    }
    
    summary_raw = await formal_summarizer_agent.execute(summarizer_payload)
    try:
        summary_json = _safe_json_loads(summary_raw)
    except json.JSONDecodeError as e:
        logger.error("Erro ao decodificar o JSON do sumário: %s", e)
        summary_json = {"erro": "summarizer output inválido", "raw": summary_raw}
        
    deal_id = raw_crm.get("deal", {}).get("id")

    if deal_id and "erro" not in summary_json:
        logger.info(f"Deal ID {deal_id} encontrado. Preparando para criar nota no Pipedrive.")
        
        note_content = _format_summary_for_note(summary_json)
        
        note_result = await pipedrive_service.create_note_for_deal(
            client=email_client,
            deal_id=deal_id,
            content=note_content
        )
        
        if note_result and "id" in note_result:
            logger.info(f"Nota criada com sucesso no Pipedrive (ID da Nota: {note_result['id']}).")
            pipedrive_actions_results.append({"action": "create_note", "status": "success", "result": note_result})
        else:
            logger.error("Falha ao criar nota no Pipedrive.")
            pipedrive_actions_results.append({"action": "create_note", "status": "failure", "result": note_result})

    # 7) Relatório final ====================================================
    report = {
        "analysis_metadata": {"conversation_id": conv_id},
        "extracted_data": extract_data,
        "temperature_analysis": temp_data,
        "kpis": kpis,
        "director_decision": director_decision,
        "advisor_recommendation": advisor_json,
        "context": {"crm_context": enriched_ctx},
        "formal_summary": summary_json,
        "pipedrive_actions": pipedrive_actions_results 
    }

    if save_result:
        logger.info("Salvando resultado da análise (%s)", conv_id)
        db = SessionLocal()
        try:
            database_service.save_email_analysis_results(db=db, analysis_data=report)
        finally:
            db.close()

    logger.info("PIPELINE EMAIL • Finalizado para %s", conv_id)
    return report
