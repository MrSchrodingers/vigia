from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json

from vigia.api import schemas, dependencies
from vigia.services import crud
from vigia.departments.negotiation_email.agents import (
    formal_summarizer_agent,
    judicial_arbiter_agent,
    conservative_advocate_agent,
    strategic_advocate_agent
)

router = APIRouter(
    prefix="/api/actions/negotiations",
    tags=["Agent Actions: Negotiations"],
    dependencies=[Depends(dependencies.get_current_user)],
)

@router.post("/{negotiation_id}/summarize", response_model=schemas.ActionResponse)
async def generate_negotiation_summary(
    negotiation_id: str,
    db: Session = Depends(dependencies.get_db)
):
    """
    Aciona o FormalSummarizerAgent para gerar um resumo de uma negociação.
    Mapeia para a função handleGenerateResume() no frontend.
    """
    neg = crud.get_negotiation_details(db, negotiation_id)
    if not neg:
        raise HTTPException(status_code=404, detail="Negotiation not found")

    # Coleta o contexto necessário para o agente
    context_payload = {
        "dados_extraidos": {"argumentos_cliente": [m.body for m in neg.email_thread.messages if "amaralvasconcellos.com.br" not in m.sender]},
        # Adicione mais contexto se necessário
    }
    
    summary_json_str = await formal_summarizer_agent.execute(context_payload)
    summary_data = json.loads(summary_json_str)
    
    # Salva o resumo no banco de dados
    neg.summary_content = summary_data.get("sumario_executivo", "Resumo indisponível.")
    db.commit()

    return {"status": "success", "data": summary_data}


@router.post("/{negotiation_id}/recommend-decisions", response_model=schemas.ActionResponse)
async def recommend_negotiation_decisions(
    negotiation_id: str,
    db: Session = Depends(dependencies.get_db)
):
    """
    Aciona o 'Júri de IAs' para recomendar as próximas ações.
    Mapeia para a função handleGenerateDecisions() no frontend.
    """
    neg = crud.get_negotiation_details(db, negotiation_id)
    if not neg:
        raise HTTPException(status_code=404, detail="Negotiation not found")

    # Contexto simulado para os agentes
    context_str = f"Analisar negociação com {neg.email_thread.participants} sobre o processo {neg.legal_process.process_number if neg.legal_process else 'N/A'}."
    
    tese_conservadora_str = await conservative_advocate_agent.execute(context_str)
    tese_estrategica_str = await strategic_advocate_agent.execute(context_str)
    
    advisor_raw = await judicial_arbiter_agent.execute(
        context=context_str,
        tese_conservadora=tese_conservadora_str,
        tese_estrategica=tese_estrategica_str,
    )
    advisor_json = json.loads(advisor_raw)
    
    # Salva a análise
    neg.analysis_content = advisor_json
    db.commit()

    return {"status": "success", "data": advisor_json}