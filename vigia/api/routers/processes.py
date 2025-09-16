from datetime import date, datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload, selectinload

from db.models import LegalProcess, ProcessDocument, TransitAnalysis, User
from vigia.api import dependencies, schemas
from vigia.departments.negotiation_email.agents.run_ai_jury_pipeline import (
    run_ai_jury_pipeline,
)
from vigia.departments.negotiation_email.services.discord_notifier import (
    send_discord_notification,
)
from vigia.departments.negotiation_email.services.process_analysis_service import (
    run_process_analysis,
)
from vigia.services import crud
from vigia.services.jusbr_service import jusbr_service

router = APIRouter(
    prefix="/api/processes",
    tags=["Legal Processes"],
    dependencies=[Depends(dependencies.get_current_user)],
)

actions_router = APIRouter(
    prefix="/api/actions/processes",
    tags=["Process Actions"],
    dependencies=[Depends(dependencies.get_current_user)],
)

transit_router = APIRouter(
    prefix="/api/proccess-analyses",
    tags=["Transit Analyses"],
    dependencies=[Depends(dependencies.get_current_user)],
)


@router.get("/", response_model=List[schemas.LegalProcess])
def read_processes(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user),
):
    processes = crud.get_processes(
        db=db, user_id=current_user.id, skip=skip, limit=limit
    )
    return processes


@router.post("/sync/{process_number}", response_model=List[schemas.LegalProcessDetails])
async def sync_and_get_process_details(
    process_number: str,
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user),
):
    """
    Busca os dados mais recentes do Jus.br, desmembra em instâncias se necessário,
    salva/atualiza no banco de dados e retorna a lista de detalhes completos.
    """
    # 1. Chamar o JusbrService para obter a lista de processos
    jusbr_data_list = await jusbr_service.get_processo_details_with_docs(process_number)

    # Verifica se o primeiro item (ou único) contém um erro
    if not jusbr_data_list or jusbr_data_list[0].get("erro"):
        raise HTTPException(
            status_code=404,
            detail=f"Process not found on Jus.br or failed to fetch: {jusbr_data_list[0].get('erro', 'Unknown error')}",
        )

    # 2. Iterar sobre cada processo retornado e fazer o "upsert"
    updated_processes_in_db = []
    for process_data in jusbr_data_list:
        process_in_db = crud.upsert_process_from_jusbr_data(
            db, process_data, user_id=current_user.id
        )
        if not process_in_db:
            raise HTTPException(
                status_code=500, detail="Failed to save process data to the database."
            )
        updated_processes_in_db.append(process_in_db)

    # 3. Retornar a lista de processos do banco, que agora estão atualizados
    return updated_processes_in_db


# --- Novas Rotas para Documentos ---


@router.get("/{process_id}/documents/{document_id}/download")
def download_process_document(
    process_id: str, document_id: str, db: Session = Depends(dependencies.get_db)
):
    """
    Baixa o conteúdo binário de um documento específico.
    """
    doc = (
        db.query(ProcessDocument)
        .filter_by(id=document_id, process_id=process_id)
        .first()
    )
    if not doc or not doc.binary_content:
        raise HTTPException(
            status_code=404, detail="Document not found or has no content."
        )

    return Response(
        content=doc.binary_content,
        media_type=doc.file_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={doc.name}"},
    )


@router.get("/{process_id}/documents/{document_id}/view")
def view_process_document(
    process_id: str, document_id: str, db: Session = Depends(dependencies.get_db)
):
    """
    Exibe (renderiza) o conteúdo de um documento no navegador, se possível.
    """
    doc = (
        db.query(ProcessDocument)
        .filter_by(id=document_id, process_id=process_id)
        .first()
    )
    if not doc or not doc.binary_content:
        raise HTTPException(
            status_code=404, detail="Document not found or has no content."
        )

    return Response(
        content=doc.binary_content,
        media_type=doc.file_type or "application/octet-stream",
    )


@actions_router.post("/{process_id}/run-ai-jury")
async def run_ai_jury_action(
    process_id: str,
    refresh: bool = Query(
        False, description="Se true, sincroniza com Jus.br antes de analisar"
    ),
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user),
):
    proc = (
        db.query(LegalProcess)
        .filter(LegalProcess.id == process_id, LegalProcess.owner_id == current_user.id)
        .first()
    )
    if not proc:
        raise HTTPException(status_code=404, detail="Process not found.")

    # opcional: sincroniza antes de analisar
    if refresh and proc.process_number:
        latest = await jusbr_service.get_processo_details_with_docs(proc.process_number)
        if latest and not latest.get("erro"):
            crud.upsert_process_from_jusbr_data(db, latest, user_id=current_user.id)
            db.refresh(proc)

    result = await run_ai_jury_pipeline(proc, db)

    # Persiste resumo/analysis no processo (se colunas existirem)
    if hasattr(proc, "summary_content"):
        proc.summary_content = result.get("summary_html")
    if hasattr(proc, "analysis_content"):
        proc.analysis_content = result  # JSONField/Text conforme seu modelo
    proc.last_update = datetime.now(timezone.utc)
    db.commit()
    db.refresh(proc)

    return result


@router.post("/{process_id}/run-ai-jury")
async def run_ai_jury_under_processes(
    process_id: str,
    refresh: bool = Query(False),
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user),
):
    return await run_ai_jury_action(
        process_id=process_id, refresh=refresh, db=db, current_user=current_user
    )


@router.get("/{process_id}", response_model=schemas.LegalProcessDetails)
def read_process_details(
    process_id: str,
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user),
):
    proc = (
        db.query(LegalProcess)
        .options(
            selectinload(LegalProcess.parties),
            selectinload(LegalProcess.documents),
            selectinload(LegalProcess.movements),
            selectinload(LegalProcess.distributions),
        )
        .filter(LegalProcess.id == process_id, LegalProcess.owner_id == current_user.id)
        .first()
    )
    if not proc:
        raise HTTPException(status_code=404, detail="Process not found")
    return proc


def create_transit_embed(process_number: str, analysis_result: dict):
    """
    Cria um embed formatado para notificação de trânsito em julgado.
    (Versão corrigida e mais robusta)
    """
    justificativa = (
        analysis_result.get("justificativa") or "Justificativa não informada."
    )
    data_transit = analysis_result.get("data_transito_julgado") or "Não informada."

    justificativa_curta = (
        (justificativa[:1021] + "...") if len(justificativa) > 1024 else justificativa
    )

    embed = {
        "title": "⚖️ Trânsito em Julgado Identificado!",
        "description": f"A análise por IA indicou que o processo está passível de encerramento.\n\n**Número:** `{process_number}`",
        "color": 3066993,
        "fields": [
            {
                "name": "Data do Trânsito em Julgado",
                "value": data_transit,
                "inline": True,
            },
            {
                "name": "Justificativa da IA",
                "value": justificativa_curta,
                "inline": False,
            },
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return embed


@actions_router.post("/{process_id}/run")
async def run_transit_analysis_action(
    process_id: str,
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user),
):
    """
    Executa a análise de IA para detectar o status de um processo (fase recursal ou trânsito em julgado).
    """
    proc = (
        db.query(LegalProcess)
        .filter(LegalProcess.id == process_id, LegalProcess.owner_id == current_user.id)
        .first()
    )
    if not proc:
        raise HTTPException(status_code=404, detail="Process not found.")

    analysis_result = await run_process_analysis(process_id=process_id, db=db)

    if "erro" in analysis_result:
        raise HTTPException(status_code=500, detail=analysis_result["erro"])

    if (
        analysis_result.get("status") == "Confirmado"
        and analysis_result.get("category") == "Trânsito em Julgado"
    ):
        message = f"✅ Trânsito em julgado detectado por IA para o processo **{proc.process_number}**."
        embed = create_transit_embed(proc.process_number, analysis_result)
        send_discord_notification(message, embed)

    return analysis_result


@transit_router.get("/", response_model=List[schemas.TransitAnalysis])
def read_transit_analyses(
    db: Session = Depends(dependencies.get_db),
    status: str | None = Query(None, description="Filtrar por status (ex: Confirmado)"),
    start_date: date | None = Query(
        None, description="Data inicial do trânsito (formato: AAAA-MM-DD)"
    ),
    end_date: date | None = Query(
        None, description="Data final do trânsito (formato: AAAA-MM-DD)"
    ),
    skip: int = 0,
    limit: int = 100,
):
    """
    Consulta as análises de trânsito em julgado salvas, com filtros.
    """

    query = db.query(TransitAnalysis).options(joinedload(TransitAnalysis.process))

    if status:
        query = query.filter(TransitAnalysis.status == status)

    if start_date:
        query = query.filter(TransitAnalysis.transit_date >= start_date)

    if end_date:
        end_datetime = datetime.combine(end_date, datetime.max.time())
        query = query.filter(TransitAnalysis.transit_date <= end_datetime)

    analyses = (
        query.order_by(TransitAnalysis.transit_date.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return analyses
