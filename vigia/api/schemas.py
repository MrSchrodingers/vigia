import datetime as dt
import uuid
from typing import Any, List, Optional

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_serializer


def parse_email_html(html_body: Optional[str]) -> str:
    """
    Limpa o HTML de um corpo de e-mail, removendo tags, assinaturas e histórico de respostas.
    """
    if not html_body:
        return ""

    soup = BeautifulSoup(html_body, "html.parser")

    # Remove blocos de resposta e assinaturas comuns do Outlook/Gmail
    for block in soup.find_all(
        "div", {"id": lambda x: x and x.startswith("divRplyFwdMsg")}
    ):
        block.decompose()
    for blockquote in soup.find_all("blockquote"):
        blockquote.decompose()

    # Remove quebras de linha excessivas e obtém o texto
    text = soup.get_text(separator="\n", strip=True)

    # Tenta remover o histórico de e-mails (heurística)
    lines = text.split("\n")
    clean_lines = []
    for line in lines:
        if line.strip().lower().startswith(("de:", "from:", "enviada em:", "sent:")):
            break
        clean_lines.append(line)

    return "\n".join(clean_lines).strip()


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
    timestamp: dt.datetime

    class Config:
        from_attributes = True


class EmailThreadLite(BaseModel):
    id: uuid.UUID
    subject: Optional[str] = None
    participants: Optional[List[str]] = None
    first_email_date: Optional[dt.datetime] = None
    last_email_date: Optional[dt.datetime] = None

    class Config:
        from_attributes = True


class Negotiation(BaseModel):
    id: uuid.UUID
    status: str
    priority: str
    debt_value: Optional[float] = None
    assigned_agent_id: uuid.UUID
    last_message: Optional[str] = None
    last_message_time: Optional[dt.datetime] = None
    message_count: int = 0
    client_name: Optional[str] = None
    process_number: Optional[str] = None

    class Config:
        from_attributes = True


class NegotiationDetails(Negotiation):
    messages: List[Message] = []
    email_thread: Optional[EmailThreadLite] = None


# --- Legal Process Schemas ---


class ProcessDistribution(BaseModel):
    id: uuid.UUID
    # Internamente usamos 'distributed_at' (evita colisão).
    # Externamente (JSON), o nome continua 'datetime' via alias.
    distributed_at: Optional[dt.datetime] = Field(
        default=None,
        serialization_alias="datetime",
        validation_alias="datetime",
    )
    orgao_julgador_id: Optional[int] = None
    orgao_julgador_nome: Optional[str] = None

    # Pydantic v2
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_serializer("distributed_at", when_used="json")
    def _ser_dt(self, v: Optional[dt.datetime], _info):
        return v.isoformat() if v else None


class ProcessPartyDocument(BaseModel):
    id: uuid.UUID
    document_type: Optional[str] = None
    document_number: Optional[str] = None

    class Config:
        from_attributes = True


class ProcessMovement(BaseModel):
    id: uuid.UUID
    date: dt.datetime
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
    # novos campos
    ajg: Optional[bool] = None
    sigilosa: Optional[bool] = None
    # documentos adicionais da parte (se o relacionamento existir)
    documents: List[ProcessPartyDocument] = []

    class Config:
        from_attributes = True


class ProcessDocument(BaseModel):
    id: uuid.UUID
    # chaves/ids externos
    external_id: Optional[str] = None
    origin_id: Optional[str] = None
    codex_id: Optional[str] = None

    # metadados principais
    name: str
    document_type: Optional[str] = None
    juntada_date: Optional[dt.datetime] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None

    # complementos do PJe
    sequence: Optional[int] = None
    secrecy_level: Optional[str] = None  # nível de sigilo do documento (ex.: 'PUBLICO')
    href_binary: Optional[str] = None
    href_text: Optional[str] = None
    type_code: Optional[int] = None
    type_name: Optional[str] = None
    pages: Optional[int] = None
    images: Optional[int] = None
    text_size: Optional[int] = None

    # conteúdo processado pelo worker (texto extraído)
    text_content: Optional[str] = None
    # Nota: conteúdo binário não é exposto aqui para evitar payloads gigantes

    class Config:
        from_attributes = True


class LegalProcess(BaseModel):
    id: uuid.UUID
    process_number: str

    # campos existentes
    classe_processual: Optional[str] = None
    assunto: Optional[str] = None
    orgao_julgador: Optional[str] = None
    status: Optional[str] = None
    valor_causa: Optional[float] = None

    # novos campos gerais
    tribunal: Optional[str] = None  # sigla
    start_date: Optional[dt.datetime] = None
    last_update: Optional[dt.datetime] = None

    # topo / flags
    secrecy_level: Optional[int] = None
    permite_peticionar: Optional[bool] = None
    fonte_dados_codex_id: Optional[int] = None
    ativo: Optional[bool] = None

    # tribunal detalhado
    tribunal_nome: Optional[str] = None
    tribunal_segmento: Optional[str] = None
    tribunal_jtr: Optional[str] = None

    # grau / instância
    instance: Optional[str] = None
    degree_sigla: Optional[str] = None
    degree_nome: Optional[str] = None
    degree_numero: Optional[int] = None

    # codificações e hierarquia
    classe_codigo: Optional[int] = None
    assunto_codigo: Optional[int] = None
    assunto_hierarquia: Optional[str] = None

    # distribuição "principal"
    distribuicao_first_datetime: Optional[dt.datetime] = None
    orgao_julgador_id: Optional[int] = None

    class Config:
        from_attributes = True


class LegalProcessLite(BaseModel):
    id: uuid.UUID
    process_number: str
    classe_processual: Optional[str] = None
    assunto: Optional[str] = None
    valor_causa: Optional[float] = None
    tribunal_nome: Optional[str] = None
    tribunal: Optional[str] = None
    degree_nome: Optional[str] = None

    class Config:
        from_attributes = True


class TransitAnalysis(BaseModel):
    id: uuid.UUID
    process_id: uuid.UUID

    category: Optional[str] = None
    subcategory: Optional[str] = None

    status: str
    justification: Optional[str] = None
    key_movements: Optional[List[str]] = None
    transit_date: Optional[dt.datetime] = None
    updated_at: dt.datetime
    analysis_raw_data: Optional[dict] = None
    created_at: dt.datetime

    process: Optional[LegalProcessLite] = None

    class Config:
        from_attributes = True


class PostSentenceAnalysis(BaseModel):
    id: uuid.UUID
    process_id: uuid.UUID

    category: str
    subcategory: Optional[str] = None
    status: str
    justification: Optional[str] = None
    key_movements: Optional[List[str]] = None
    appeal_date: Optional[dt.datetime] = None
    updated_at: dt.datetime
    created_at: dt.datetime
    analysis_raw_data: Optional[dict] = None

    process: Optional[LegalProcessLite] = None

    class Config:
        from_attributes = True


class CPJParty(BaseModel):
    qualificacao: int
    nome: str
    documento: Optional[str]
    tipo_pessoa: Optional[str]

    class Config:
        orm_mode = True


class CPJMovement(BaseModel):
    data_andamento: Optional[dt.datetime]
    texto_andamento: Optional[str]

    class Config:
        orm_mode = True


class CPJProcessDetails(BaseModel):
    id: uuid.UUID
    legal_process_id: uuid.UUID
    cpj_cod_processo: int
    ficha: Optional[str]
    incidente: Optional[int]
    numero_processo: Optional[str]
    juizo: Optional[str]
    valor_causa: Optional[float]
    entrada_date: Optional[dt.datetime]
    last_update_cpj: Optional[dt.datetime]
    parties: List[CPJParty] = []
    movements: List[CPJMovement] = []

    class Config:
        orm_mode = True


class LegalProcessDetails(LegalProcess):
    movements: List[ProcessMovement] = []
    parties: List[ProcessParty] = []
    documents: List[ProcessDocument] = []
    distributions: List[ProcessDistribution] = []
    summary_content: Optional[str] = None
    analysis_content: Optional[dict] = None
    raw_data: Optional[dict] = None

    transit_analysis: Optional[TransitAnalysis] = None

    class Config:
        from_attributes = True


# --- Chat Schemas ---
class ChatMessageBase(BaseModel):
    content: str


class ChatMessageCreate(ChatMessageBase):
    pass


class ChatMessage(ChatMessageBase):
    id: uuid.UUID
    role: str
    timestamp: dt.datetime

    class Config:
        from_attributes = True


class ChatSession(BaseModel):
    id: uuid.UUID
    title: str
    created_at: dt.datetime
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
