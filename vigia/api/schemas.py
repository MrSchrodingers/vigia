from bs4 import BeautifulSoup
from pydantic import BaseModel, EmailStr
from typing import Any, List, Optional
from datetime import datetime
import uuid

def parse_email_html(html_body: Optional[str]) -> str:
    """
    Limpa o HTML de um corpo de e-mail, removendo tags, assinaturas e histórico de respostas.
    """
    if not html_body:
        return ""
    
    soup = BeautifulSoup(html_body, 'html.parser')
    
    # Remove blocos de resposta e assinaturas comuns do Outlook/Gmail
    for block in soup.find_all("div", {"id": lambda x: x and x.startswith('divRplyFwdMsg')}):
        block.decompose()
    for blockquote in soup.find_all("blockquote"):
        blockquote.decompose()
    
    # Remove quebras de linha excessivas e obtém o texto
    text = soup.get_text(separator='\n', strip=True)
    
    # Tenta remover o histórico de e-mails (heurística)
    lines = text.split('\n')
    clean_lines = []
    for line in lines:
        if line.strip().lower().startswith(('de:', 'from:', 'enviada em:', 'sent:')):
            break
        clean_lines.append(line)
        
    return '\n'.join(clean_lines).strip()

# --- Base Schemas ---
class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    email: Optional[str] = None

# --- User Schemas ---
class UserBase(BaseModel):
    email: EmailStr

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: uuid.UUID
    is_active: bool

    class Config:
        from_attributes = True

# --- Message & Negotiation Schemas ---
class Message(BaseModel):
    id: uuid.UUID
    sender: str
    content: str 
    timestamp: datetime 

    class Config:
        from_attributes = True
        @classmethod
        def from_orm(cls, obj):
            # ✅ A MÁGICA ACONTECE AQUI!
            # O corpo do e-mail (obj.body) é parseado antes de ser enviado.
            return super().from_orm({
                'id': obj.id,
                'sender': obj.sender,
                'content': parse_email_html(obj.body), # Limpa o HTML
                'timestamp': obj.sent_datetime,
            })

class Negotiation(BaseModel):
    id: uuid.UUID
    status: str
    priority: str
    debt_value: Optional[float] = None
    assigned_agent_id: uuid.UUID
    last_message: Optional[str] = None
    last_message_time: Optional[datetime] = None
    message_count: int = 0
    client_name: Optional[str] = None
    process_number: Optional[str] = None
    
    class Config:
        from_attributes = True

class NegotiationDetails(Negotiation):
    messages: List[Message] = []
    email_thread: Optional[Any] = None

# --- Legal Process Schemas ---
class ProcessMovement(BaseModel):
    id: uuid.UUID
    date: datetime
    description: str

    class Config:
        from_attributes = True

class ProcessParty(BaseModel):
    id: uuid.UUID
    polo: str
    name: str
    document_type: Optional[str] = None
    document_number: Optional[str] = None
    representatives: Optional[List[dict]] = []

    class Config:
        from_attributes = True

class ProcessDocument(BaseModel):
    id: uuid.UUID
    external_id: Optional[str] = None
    name: str
    document_type: Optional[str] = None
    juntada_date: datetime
    file_type: Optional[str] = None
    file_size: Optional[int] = None

    class Config:
        from_attributes = True

class LegalProcess(BaseModel):
    id: uuid.UUID
    process_number: str
    classe_processual: Optional[str] = None
    assunto: Optional[str] = None
    orgao_julgador: Optional[str] = None
    status: Optional[str] = None
    valor_causa: Optional[float] = None
    
    class Config:
        from_attributes = True

class LegalProcessDetails(LegalProcess):
    movements: List[ProcessMovement] = []
    parties: List[ProcessParty] = []
    documents: List[ProcessDocument] = []
    summary_content: Optional[str] = None
    analysis_content: Optional[dict] = None
    
# --- Chat Schemas ---
class ChatMessageBase(BaseModel):
    content: str

class ChatMessageCreate(ChatMessageBase):
    pass

class ChatMessage(ChatMessageBase):
    id: uuid.UUID
    role: str
    timestamp: datetime

    class Config:
        from_attributes = True

class ChatSession(BaseModel):
    id: uuid.UUID
    title: str
    created_at: datetime
    owner_id: uuid.UUID

    class Config:
        from_attributes = True

class ChatSessionDetails(ChatSession):
    messages: List[ChatMessage] = []
    
class ActionResponse(BaseModel):
    status: str
    message: Optional[str] = None
    data: Optional[Any] = None

class JusbrStatus(BaseModel):
    is_active: bool
    message: Optional[str] = None
    
