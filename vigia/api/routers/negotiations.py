from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from vigia.api import schemas, dependencies
from vigia.services import crud
from db.models import User

router = APIRouter(
    prefix="/api/negotiations",
    tags=["Negotiations"],
    dependencies=[Depends(dependencies.get_current_user)],
)

@router.get("/", response_model=List[schemas.Negotiation])
def read_negotiations(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user)
):
    results = crud.get_negotiations(db=db, user_id=current_user.id, skip=skip, limit=limit)
    
    # Esta parte adapta o resultado da query para o schema Pydantic
    # Pode ser otimizado com um DTO mais direto no futuro
    response_data = []
    for neg, count, last_time in results:
        # Lógica para pegar um nome de cliente (exemplo, pode ser melhorado)
        client_name = "Cliente Exemplo"
        if neg.email_thread and neg.email_thread.participants:
            client_emails = [p for p in neg.email_thread.participants if '@' in p and 'amaralvasconcellos.com.br' not in p]
            if client_emails:
                client_name = client_emails[0]

        response_data.append({
            **neg.__dict__,
            "message_count": count,
            "last_message_time": last_time,
            "client_name": client_name,
            "process_number": neg.legal_process.process_number if neg.legal_process else "N/A"
        })
    return response_data


@router.get("/{negotiation_id}", response_model=schemas.NegotiationDetails)
def read_negotiation_details(negotiation_id: str, db: Session = Depends(dependencies.get_db)):
    db_negotiation = crud.get_negotiation_details(db, negotiation_id=negotiation_id)
    if db_negotiation is None:
        raise HTTPException(status_code=404, detail="Negotiation not found")
    
    # Mapeia as mensagens do email_thread para o schema correto
    messages = [schemas.Message.from_orm(msg) for msg in db_negotiation.email_thread.messages]
    
    return {**db_negotiation.__dict__, "messages": messages}