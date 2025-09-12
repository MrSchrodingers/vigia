from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from vigia.api import schemas, dependencies
from vigia.config import settings
from vigia.services import crud
from db.models import User, Negotiation, EmailThread

ORG_DOMAINS = set(getattr(settings, "ORG_DOMAINS", ["amaralvasconcellos.com.br","pavcob.com.br"]))

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

def _role_from_sender(sender: str) -> str:
    s = (sender or "").lower()
    return "agent" if any(d in s for d in ORG_DOMAINS) else "client"

@router.get("/{negotiation_id}", response_model=schemas.NegotiationDetails)
def read_negotiation_details(negotiation_id: str, db: Session = Depends(dependencies.get_db)):
    db_neg = db.query(Negotiation).options(
        joinedload(Negotiation.email_thread).joinedload(EmailThread.messages)
    ).filter(Negotiation.id == negotiation_id).first()

    if db_neg is None:
        raise HTTPException(status_code=404, detail="Negotiation not found")

    # Serializa mensagens (limpando HTML)
    msgs: List[schemas.Message] = []
    if db_neg.email_thread and db_neg.email_thread.messages:
        for m in db_neg.email_thread.messages:
            msgs.append(
                schemas.Message(
                    id=m.id,
                    sender=m.sender or "",
                    content=schemas.parse_email_html(m.body),
                    timestamp=m.sent_datetime,
                )
            )

    # Thread “leve” (sem relações para evitar recursion / tipos desconhecidos)
    thread_lite = schemas.EmailThreadLite.model_validate(db_neg.email_thread) if db_neg.email_thread else None

    # Derive alguns campos que você já usa na lista
    participants = [p for p in (db_neg.email_thread.participants or []) if p]
    client_name = "Cliente Desconhecido"
    for p in participants:
        low = p.lower()
        if not any(d in low for d in ORG_DOMAINS) and "@" in p:
            client_name = p.split("@")[0].replace(".", " ").title()
            break

    details = schemas.NegotiationDetails(
        id=db_neg.id,
        status=db_neg.status,
        priority=db_neg.priority,
        debt_value=db_neg.debt_value,
        assigned_agent_id=db_neg.assigned_agent_id,
        last_message=None,
        last_message_time=None,
        message_count=len(msgs),
        client_name=client_name,
        process_number=db_neg.legal_process.process_number if db_neg.legal_process else "N/A",
        messages=msgs,
        email_thread=thread_lite,
    )
    return details