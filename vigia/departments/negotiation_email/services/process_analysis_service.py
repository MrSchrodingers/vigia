import json
import re
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from db import models
from vigia.departments.negotiation_email.services.process_orchestrator_service import ProcessStatusOrchestrator

def _parse_date_from_str(text: str) -> datetime | None:
    if not text:
        return None
    match = re.search(r'(\d{2})/(\d{2})/(\d{4})', text)
    if match:
        try:
            return datetime.strptime(match.group(0), '%d/%m/%Y').replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None

def _save_transit_analysis(db: Session, proc: models.LegalProcess, result: dict):
    """Lógica idempotente para salvar/atualizar uma análise de trânsito em julgado."""
    existing_analysis = db.query(models.TransitAnalysis).filter_by(process_id=proc.id).first()

    date_text = " ".join(result.get("movimentacoes_chave") or [])
    transit_date = _parse_date_from_str(date_text)
    if not transit_date:
        transit_date = _parse_date_from_str(result.get("justificativa", ""))
    
    data = {
        "category": result.get("category"),
        "subcategory": result.get("subcategory"),
        "status": result.get("status"),
        "justification": result.get("justificativa"),
        "key_movements": result.get("movimentacoes_chave"),
        "transit_date": transit_date,
        "analysis_raw_data": result,
    }

    if existing_analysis:
        for key, value in data.items():
            setattr(existing_analysis, key, value)
    else:
        new_analysis = models.TransitAnalysis(process_id=proc.id, **data)
        db.add(new_analysis)

def _save_post_sentence_analysis(db: Session, proc: models.LegalProcess, result: dict):
    """Lógica idempotente para salvar/atualizar uma análise de fase recursal."""
    existing_analysis = db.query(models.PostSentenceAnalysis).filter_by(process_id=proc.id).first()

    appeal_date = _parse_date_from_str(result.get("data_interposicao_recurso", ""))

    data = {
        "category": result.get("category"),
        "subcategory": result.get("subcategory"),
        "status": result.get("status"),
        "justification": result.get("justificativa"),
        "key_movements": result.get("movimentacoes_chave"),
        "appeal_date": appeal_date,
        "analysis_raw_data": result,
    }

    if existing_analysis:
        for key, value in data.items():
            setattr(existing_analysis, key, value)
    else:
        new_analysis = models.PostSentenceAnalysis(process_id=proc.id, **data)
        db.add(new_analysis)


async def run_process_analysis(process_id: str, db: Session) -> dict:
    """
    Orquestra a análise de status de um processo, decidindo qual tipo de análise
    realizar e onde persistir o resultado.
    """
    proc = db.query(models.LegalProcess).filter(models.LegalProcess.id == process_id).first()
    if not proc:
        return {"erro": "Processo não encontrado"}

    # 1. Chamar o orquestrador para obter o resultado da análise
    orchestrator = ProcessStatusOrchestrator(db)
    analysis_result_raw = await orchestrator.analyze(proc)

    try:
        analysis_result = json.loads(analysis_result_raw) if isinstance(analysis_result_raw, str) else analysis_result_raw
    except (json.JSONDecodeError, TypeError):
        return {"erro": "Falha ao decodificar a resposta do agente ou orquestrador."}

    # 2. DECIDIR ONDE PERSISTIR com base na categoria
    category = analysis_result.get("category")
    if category == "Fase Recursal":
        _save_post_sentence_analysis(db, proc, analysis_result)
    elif category in ["Trânsito em Julgado", "Em Andamento", "Análise Inconclusiva"]:
        # Persiste todos os outros casos na tabela de Trânsito, que serve como status geral.
        _save_transit_analysis(db, proc, analysis_result)
    else:
        # Não salva se a categoria for desconhecida
        print(f"Categoria desconhecida recebida do orquestrador: {category}")


    # 3. Atualizar campos gerais do processo e comitar
    if hasattr(proc, 'analysis_content'):
        proc.analysis_content = analysis_result
    proc.last_update = datetime.now(timezone.utc)
    db.commit()

    return analysis_result