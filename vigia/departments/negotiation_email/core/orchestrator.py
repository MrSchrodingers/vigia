import logging
import asyncio
import json
import re
from datetime import datetime
from typing import Dict, Any, Tuple, Optional, Union

from sqlalchemy.orm import Session
from db.session import SessionLocal
from db import models
from vigia.services import database_service

# ==== Agents ================================================================
from ..agents import (
    context_miner_agent,
    context_synthesizer_agent,
    extraction_subject_agent,
    extraction_legal_financial_agent,
    extraction_stage_agent,
    extraction_manager_agent,
    temperature_behavioral_agent,
    director_agent,
    judicial_negotiation_advisor_agent,
)
# from .tools import execute_email_tool_call  # TODO: habilitar quando pronto

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Utilitários internos
# ---------------------------------------------------------------------------


def _safe_json_loads(text: Union[str, bytes]) -> Dict[str, Any]:
    """Tenta converter *qualquer* string para dict JSON.

    1. Remove etiquetas markdown (` ```json` etc.)
    2. Busca o primeiro bloco {...} balanceado.
    3. Se tudo falhar, levanta JSONDecodeError original.
    """
    if isinstance(text, bytes):
        text = text.decode()
    clean = text.strip()
    # remove fences de markdown
    if clean.startswith("```"):
        clean = re.sub(r"```[a-zA-Z]*", "", clean).strip().rstrip("`").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError as e:
        logger.warning("JSON original inválido (%s). Tentando heurística…", e)
        m = re.search(r"\{.*\}", clean, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError as e2:
                logger.error("Heurística falhou: %s", e2)
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
    history = "\n\n".join(
        f"De: {m.sender}\nData: {m.sent_datetime.strftime('%d/%m/%Y %H:%M')}\n\n{m.body}"
        for m in messages
    )
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

async def run_extraction_department(subject: str, history_txt: str) -> str:
    logger.info("-- Extracting factual data")
    reports = await asyncio.gather(
        extraction_subject_agent.execute(subject),
        extraction_legal_financial_agent.execute(history_txt),
        extraction_stage_agent.execute(history_txt),
    )
    return await extraction_manager_agent.execute(*reports)


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
    extract_str, temp_str = await asyncio.gather(
        run_extraction_department(thread_meta["subject"], history_plus_ctx),
        run_temperature_department(full_history, thread_meta),
    )

    extract_data = _safe_json_loads(extract_str)
    temp_data = _safe_json_loads(temp_str)

    # 3) KPIs ===============================================================
    kpis = _build_kpis(thread_meta, extract_data)

    # 4) Diretoria ==========================================================
    director_raw = await director_agent.execute(json.dumps(extract_data), json.dumps(temp_data), conv_id)
    try:
        director_json = _safe_json_loads(director_raw)
    except json.JSONDecodeError:
        director_json = {"erro": "output inválido", "raw": director_raw}

    if "acao" in director_json:
        logger.info("Diretor solicitou ação %s", director_json["acao"].get("nome_ferramenta"))
        director_json = {
            "acao_executada": director_json["acao"],
            "resultado_execucao": "simulado",
        }

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

    # 6) Relatório final ====================================================
    report = {
        "analysis_metadata": {"conversation_id": conv_id},
        "extracted_data": extract_data,
        "temperature_analysis": temp_data,
        "kpis": kpis,
        "director_decision": director_json,
        "advisor_recommendation": advisor_json,
        "context": {"crm_context": enriched_ctx},
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
