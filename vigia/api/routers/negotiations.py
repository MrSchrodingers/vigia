from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from vigia.api import schemas, dependencies
from vigia.services import crud
from db.models import User, Negotiation, EmailThread

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
    
    response_data = []
    for neg, count, last_time, last_message_body in results:
        client_name = "Cliente Desconhecido"
        # Lógica aprimorada para extrair o nome do cliente
        if neg.email_thread and neg.email_thread.participants:
            # Encontra o primeiro e-mail que não é do seu domínio
            client_emails = [
                p for p in neg.email_thread.participants 
                if p and '@' in p and 'amaralvasconcellos.com.br' not in p and 'pavcob.com.br' not in p
            ]
            if client_emails:
                # Usa a parte antes do @ como nome do cliente
                client_name = client_emails[0].split('@')[0].replace('.', ' ').title()

        response_data.append({
            "id": neg.id,
            "status": neg.status,
            "priority": neg.priority,
            "debt_value": neg.debt_value,
            "assigned_agent_id": neg.assigned_agent_id,
            "message_count": count,
            "last_message_time": last_time,
            "last_message": schemas.parse_email_html(last_message_body), # Limpa a última mensagem
            "client_name": client_name,
            "process_number": neg.legal_process.process_number if neg.legal_process else "N/A"
        })
    return response_data


@router.get("/{negotiation_id}", response_model=schemas.NegotiationDetails)
def read_negotiation_details(negotiation_id: str, db: Session = Depends(dependencies.get_db)):
    # Usamos joinedload para buscar a thread e as mensagens de uma só vez (mais eficiente)
    db_negotiation = db.query(Negotiation).options(
        joinedload(Negotiation.email_thread).joinedload(EmailThread.messages)
    ).filter(Negotiation.id == negotiation_id).first()

    if db_negotiation is None:
        raise HTTPException(status_code=404, detail="Negotiation not found")
    
    # O schema Pydantic agora cuida do parsing de cada mensagem automaticamente
    # graças à função from_orm que modificamos.
    return db_negotiation