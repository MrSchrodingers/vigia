
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from vigia.api import schemas, dependencies
from vigia.services import crud, chat_service
from db.models import User

router = APIRouter(
    prefix="/api/chat",
    tags=["Chat"],
    dependencies=[Depends(dependencies.get_current_user)],
)

@router.post("/sessions/{session_id}/messages", response_model=schemas.ChatMessage)
async def post_chat_message(
    session_id: str,
    message: schemas.ChatMessageCreate,
    db: Session = Depends(dependencies.get_db),
    current_user: User = Depends(dependencies.get_current_user)
):
    session = crud.get_chat_session(db, session_id=session_id, user_id=current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")

    # Salva a mensagem do usuário
    crud.create_chat_message(db, message=message, session_id=session_id, role="user")

    # Gera e salva a resposta da IA
    assistant_response_content = await chat_service.generate_assistant_response(
        db=db, 
        user_message=message.content, 
        session_id=session_id
    )
    
    assistant_message_schema = schemas.ChatMessageCreate(content=assistant_response_content)
    assistant_message = crud.create_chat_message(
        db, 
        message=assistant_message_schema,
        session_id=session_id, 
        role="assistant"
    )

    return assistant_message