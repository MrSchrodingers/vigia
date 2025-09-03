from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session
from typing import List

from vigia.api import schemas, dependencies
from vigia.services import crud, jusbr_service
from db.models import User, ProcessDocument

router = APIRouter(
    prefix="/api/processes",
    tags=["Legal Processes"],
    dependencies=[Depends(dependencies.get_current_user)],
)

@router.get("/", response_model=List[schemas.LegalProcess])
def read_processes(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user)
):
    processes = crud.get_processes(db=db, user_id=current_user.id, skip=skip, limit=limit)
    return processes

@router.post("/sync/{process_number}", response_model=schemas.LegalProcessDetails)
async def sync_and_get_process_details(
    process_number: str,
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user)
):
    """
    Busca os dados mais recentes do Jus.br para um número de processo,
    salva/atualiza no banco de dados e retorna os detalhes completos.
    """
    # 1. Chamar o JusbrService para obter os dados brutos e os binários
    jusbr_data = await jusbr_service.get_processo_details_with_docs(process_number)
    if not jusbr_data or jusbr_data.get("erro"):
        raise HTTPException(
            status_code=404, 
            detail=f"Process not found on Jus.br or failed to fetch: {jusbr_data.get('erro', 'Unknown error')}"
        )
        
    # 2. Chamar o CRUD para fazer o "upsert" no banco de dados
    process_in_db = crud.upsert_process_from_jusbr_data(db, jusbr_data, user_id=current_user.id)
    if not process_in_db:
        raise HTTPException(status_code=500, detail="Failed to save process data to the database.")

    # 3. Retornar os dados do banco, que agora estão atualizados
    return process_in_db

# --- Novas Rotas para Documentos ---

@router.get("/{process_id}/documents/{document_id}/download")
def download_process_document(process_id: str, document_id: str, db: Session = Depends(dependencies.get_db)):
    """
    Baixa o conteúdo binário de um documento específico.
    """
    doc = db.query(ProcessDocument).filter_by(id=document_id, process_id=process_id).first()
    if not doc or not doc.binary_content:
        raise HTTPException(status_code=404, detail="Document not found or has no content.")
    
    return Response(
        content=doc.binary_content, 
        media_type=doc.file_type or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={doc.name}"}
    )

@router.get("/{process_id}/documents/{document_id}/view")
def view_process_document(process_id: str, document_id: str, db: Session = Depends(dependencies.get_db)):
    """
    Exibe (renderiza) o conteúdo de um documento no navegador, se possível.
    """
    doc = db.query(ProcessDocument).filter_by(id=document_id, process_id=process_id).first()
    if not doc or not doc.binary_content:
        raise HTTPException(status_code=404, detail="Document not found or has no content.")
        
    return Response(
        content=doc.binary_content,
        media_type=doc.file_type or "application/octet-stream"
    )
    
# @router.get("/{process_id}", response_model=schemas.LegalProcessDetails)
# def read_process_details(process_id: str, db: Session = Depends(dependencies.get_db)):
#     db_process = crud.get_process_details(db, process_id=process_id)
#     if db_process is None:
#         raise HTTPException(status_code=404, detail="Process not found")
#     return db_process