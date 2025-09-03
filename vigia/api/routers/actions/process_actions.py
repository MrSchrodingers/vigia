# vigia/api/routers/actions/process_actions.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json

from vigia.api import schemas, dependencies
from vigia.services import crud
from vigia.departments.negotiation_email.agents import legal_context_synthesizer_agent

router = APIRouter(
    prefix="/api/actions/processes",
    tags=["Agent Actions: Legal Processes"],
    dependencies=[Depends(dependencies.get_current_user)],
)

@router.post("/{process_id}/summarize", response_model=schemas.ActionResponse)
async def generate_process_summary(
    process_id: str,
    db: Session = Depends(dependencies.get_db)
):
    """
    Gera um resumo textual de um processo legal usando um agente.
    Mapeia para a função handleGenerateResume() no frontend.
    """
    process = crud.get_process_details(db, process_id)
    if not process:
        raise HTTPException(status_code=404, detail="Process not found")

    # Usa o LegalContextSynthesizerAgent para estruturar e resumir
    # (assumindo que ele também pode gerar o campo 'resumo_textual')
    # Idealmente, você teria um agente só para sumarização de processos.
    
    # Simulando um payload de entrada para o agente
    process_data_payload = {"dados_gerais": {"numero_processo": process.process_number, "classe": "Ação de Cobrança"}}
    
    summary_raw = await legal_context_synthesizer_agent.execute(process_data_payload)
    summary_json = json.loads(summary_raw)
    
    summary_text = summary_json.get("resumo_textual", "Resumo não pôde ser gerado.")
    
    process.summary_content = summary_text
    db.commit()
    
    return {"status": "success", "data": {"resume": summary_text}}


@router.post("/{process_id}/generate-pdf", response_model=schemas.ActionResponse)
async def generate_process_pdf(process_id: str):
    """
    Inicia a geração de um PDF para o processo em background.
    Mapeia para a função handleGeneratePDF().
    """
    # Em um sistema real, isso iniciaria uma tarefa Celery/background.
    # A tarefa geraria o PDF e salvaria em um storage.
    # Por agora, retornamos um sucesso simulado.
    
    pdf_url = f"/api/files/processes/{process_id}/report.pdf" # URL simulada
    return {"status": "processing", "message": "PDF generation started", "data": {"url": pdf_url}}