import uuid

from passlib.context import CryptContext
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

from lib.uuid import uuid7 as lib_uuid7

Base = declarative_base()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def as_std_uuid():
    return uuid.UUID(str(lib_uuid7()))


# --- Modelos de Autenticação e Usuários ---
class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)

    negotiations = relationship("Negotiation", back_populates="assigned_agent")
    processes = relationship("LegalProcess", back_populates="owner")
    chat_sessions = relationship("ChatSession", back_populates="owner")

    def verify_password(self, plain_password):
        return pwd_context.verify(plain_password, self.hashed_password)


# --- Modelos Legais e de Negociação ---


class CPJProcess(Base):
    """Armazena uma cópia dos dados principais do processo vindos do CPJ."""

    __tablename__ = "cpj_processes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)

    # Chave estrangeira para o nosso processo principal
    legal_process_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal_processes.id"),
        nullable=False,
        unique=True,
    )

    # Campos do CPJ
    cpj_cod_processo = Column(Integer, unique=True, index=True, nullable=False)
    cpj_cod_agrupador = Column(Integer, index=True)
    ficha = Column(String(20), index=True)
    incidente = Column(Integer)
    numero_processo = Column(String, index=True)
    juizo = Column(String)
    valor_causa = Column(Float)
    entrada_date = Column(DateTime(timezone=True))
    last_update_cpj = Column(DateTime(timezone=True), index=True)

    # Relacionamentos
    legal_process = relationship("LegalProcess", backref="cpj_data")
    parties = relationship(
        "CPJParty", back_populates="process", cascade="all, delete-orphan"
    )
    movements = relationship(
        "CPJMovement", back_populates="process", cascade="all, delete-orphan"
    )


class CPJParty(Base):
    """Partes (envolvidos) de um processo do CPJ."""

    __tablename__ = "cpj_parties"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    process_id = Column(
        UUID(as_uuid=True), ForeignKey("cpj_processes.id"), nullable=False
    )

    qualificacao = Column(Integer)  # 1 para autor, 2 para réu
    nome = Column(String, nullable=False)
    documento = Column(String)
    tipo_pessoa = Column(String(1))  # 'F' ou 'J'

    process = relationship("CPJProcess", back_populates="parties")


class CPJMovement(Base):
    """Andamentos de um processo do CPJ."""

    __tablename__ = "cpj_movements"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    process_id = Column(
        UUID(as_uuid=True), ForeignKey("cpj_processes.id"), nullable=False
    )

    data_andamento = Column(DateTime(timezone=True), index=True)
    texto_andamento = Column(Text)

    process = relationship("CPJProcess", back_populates="movements")


class LegalProcess(Base):
    __tablename__ = "legal_processes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    process_number = Column(String, index=True, nullable=False)
    numero_unico_incidencia = Column(
        String, unique=True, index=True, nullable=True
    )  # Identificador único para cada instância (processo + classe)
    grupo_incidencia = Column(
        String, index=True, nullable=True
    )  # "Flag" para agrupar instâncias do mesmo processo
    classe_processual = Column(String, nullable=True)
    assunto = Column(String, nullable=True)
    orgao_julgador = Column(String, nullable=True)
    tribunal = Column(String, nullable=True)
    status = Column(String, index=True)
    valor_causa = Column(Float, nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=True)
    last_update = Column(DateTime(timezone=True), nullable=True)
    summary_content = Column(Text, nullable=True)
    analysis_content = Column(JSON, nullable=True)
    raw_data = Column(JSON, nullable=True)  # Campo para guardar o JSON bruto do Jus.br
    secrecy_level = Column(Integer, nullable=True)  # nivelSigilo
    instance = Column(String, nullable=True)  # tramitacaoAtual.instancia
    degree_sigla = Column(String(8), nullable=True)  # tramitacaoAtual.grau.sigla
    degree_nome = Column(String(32), nullable=True)  # tramitacaoAtual.grau.nome
    degree_numero = Column(Integer, nullable=True)  # tramitacaoAtual.grau.numero

    # distribuição "principal" (se quiser guardar o primeiro item também aqui)
    distribuicao_first_datetime = Column(DateTime(timezone=True), nullable=True)
    orgao_julgador_id = Column(Integer, nullable=True)  # id numérico

    # tribunal detalhado
    tribunal_nome = Column(String, nullable=True)
    tribunal_segmento = Column(String, nullable=True)
    tribunal_jtr = Column(String, nullable=True)

    # classe/assunto (códigos)
    classe_codigo = Column(Integer, nullable=True)
    assunto_codigo = Column(Integer, nullable=True)
    assunto_hierarquia = Column(Text, nullable=True)

    permite_peticionar = Column(Boolean, nullable=True)
    fonte_dados_codex_id = Column(Integer, nullable=True)  # idFonteDadosCodex
    ativo = Column(Boolean, nullable=True)

    cpj_ficha = Column(String(20), index=True, nullable=True)
    cpj_incidente = Column(Integer, nullable=True)
    cpj_cod_processo = Column(
        Integer, index=True, nullable=True
    )  # Para referenciar o código interno do CPJ
    cpj_cod_agrupador = Column(
        Integer, index=True, nullable=True
    )  # Para agrupar incidentes

    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    owner = relationship("User", back_populates="processes")

    movements = relationship(
        "ProcessMovement", back_populates="process", cascade="all, delete-orphan"
    )
    parties = relationship(
        "ProcessParty", back_populates="process", cascade="all, delete-orphan"
    )
    documents = relationship(
        "ProcessDocument", back_populates="process", cascade="all, delete-orphan"
    )
    negotiations = relationship("Negotiation", back_populates="legal_process")
    transit_analysis = relationship(
        "TransitAnalysis",
        back_populates="process",
        uselist=False,
        cascade="all, delete-orphan",
    )
    post_sentence_analysis = relationship(
        "PostSentenceAnalysis",
        back_populates="process",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ProcessDistribution(Base):
    __tablename__ = "process_distributions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    datetime = Column(DateTime(timezone=True), nullable=False)
    orgao_julgador_id = Column(Integer, nullable=True)
    orgao_julgador_nome = Column(String, nullable=True)

    process_id = Column(
        UUID(as_uuid=True), ForeignKey("legal_processes.id"), nullable=False
    )
    process = relationship("LegalProcess", backref="distributions")


class ProcessPartyDocument(Base):
    __tablename__ = "process_party_documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    document_type = Column(String, nullable=True)
    document_number = Column(String, nullable=True)

    party_id = Column(
        UUID(as_uuid=True), ForeignKey("process_parties.id"), nullable=False
    )
    party = relationship("ProcessParty", backref="documents")


class ProcessMovement(Base):
    __tablename__ = "process_movements"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    date = Column(DateTime(timezone=True), nullable=False)
    description = Column(Text, nullable=False)

    process_id = Column(
        UUID(as_uuid=True), ForeignKey("legal_processes.id"), nullable=False
    )
    process = relationship("LegalProcess", back_populates="movements")


class ProcessParty(Base):
    __tablename__ = "process_parties"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    polo = Column(String(50), nullable=False)  # ATIVO, PASSIVO
    name = Column(String, nullable=False)
    document_type = Column(String, nullable=True)  # CPF, CNPJ
    document_number = Column(String, nullable=True)
    representatives = Column(JSON, nullable=True)  # Para armazenar advogados
    ajg = Column(Boolean, nullable=True)  # assistenciaJudiciariaGratuita
    sigilosa = Column(Boolean, nullable=True)  # sigilosa

    process_id = Column(
        UUID(as_uuid=True), ForeignKey("legal_processes.id"), nullable=False
    )
    process = relationship("LegalProcess", back_populates="parties")


class ProcessDocument(Base):
    __tablename__ = "process_documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    external_id = Column(String, index=True, nullable=True)  # idOrigem ou idCodex
    name = Column(String, nullable=False)
    document_type = Column(String, nullable=True)
    juntada_date = Column(DateTime(timezone=True), nullable=False)
    file_type = Column(String, nullable=True)  # ex: application/pdf
    file_size = Column(Integer, nullable=True)
    text_content = Column(Text, nullable=True)
    binary_content = Column(LargeBinary, nullable=True)  # ARMAZENA O ARQUIVO
    sequence = Column(Integer, nullable=True)  # documentos[].sequencia
    secrecy_level = Column(String, nullable=True)  # documentos[].nivelSigilo
    origin_id = Column(String, nullable=True)  # documentos[].idOrigem
    codex_id = Column(String, nullable=True)  # documentos[].idCodex
    href_binary = Column(String, nullable=True)  # documentos[].hrefBinario
    href_text = Column(String, nullable=True)  # documentos[].hrefTexto
    type_code = Column(Integer, nullable=True)  # documentos[].tipo.codigo
    type_name = Column(String, nullable=True)  # documentos[].tipo.nome
    pages = Column(Integer, nullable=True)  # documentos[].arquivo.quantidadePaginas
    images = Column(Integer, nullable=True)  # documentos[].arquivo.quantidadeImagens
    text_size = Column(Integer, nullable=True)  # documentos[].arquivo.tamanhoTexto

    process_id = Column(
        UUID(as_uuid=True), ForeignKey("legal_processes.id"), nullable=False
    )
    process = relationship("LegalProcess", back_populates="documents")

    __table_args__ = (
        UniqueConstraint("process_id", "sequence", name="uq_doc_process_sequence"),
    )


class TransitAnalysis(Base):
    __tablename__ = "transit_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)

    process_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal_processes.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    category = Column(
        String, index=True, nullable=True
    )  # Ex: "Trânsito em Julgado", "Fase Recursal", "Em Andamento"
    subcategory = Column(
        String, nullable=True
    )  # Ex: "Confirmado por Certidão", "Apelação Pendente"

    status = Column(
        String, index=True, nullable=False
    )  # Ex: "Confirmado", "Não Transitado"
    justification = Column(Text, nullable=True)
    key_movements = Column(JSON, nullable=True)
    transit_date = Column(
        DateTime(timezone=True), nullable=True
    )  # Data extraída, se houver
    analysis_raw_data = Column(JSON, nullable=True)  # Guarda o JSON bruto da IA

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), default=func.now()
    )

    # Relação com o processo
    process = relationship("LegalProcess", back_populates="transit_analysis")


class PostSentenceAnalysis(Base):
    __tablename__ = "post_sentence_analyses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    process_id = Column(
        UUID(as_uuid=True),
        ForeignKey("legal_processes.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    category = Column(String, default="Fase Recursal", nullable=False)
    subcategory = Column(
        String, nullable=True
    )  # Ex: "Em Apelação", "Embargos de Declaração Opostos"

    status = Column(
        String, index=True, nullable=False
    )  # Ex: "Pendente de Julgamento", "Aguardando Contrarrazões"
    justification = Column(Text, nullable=True)
    key_movements = Column(JSON, nullable=True)
    appeal_date = Column(
        DateTime(timezone=True), nullable=True
    )  # Data da interposição do recurso
    analysis_raw_data = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), default=func.now()
    )

    process = relationship("LegalProcess", back_populates="post_sentence_analysis")


class Negotiation(Base):
    __tablename__ = "negotiations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    status = Column(String, default="active", index=True)
    priority = Column(String, default="medium")
    debt_value = Column(Float, nullable=True)
    summary_content = Column(Text, nullable=True)
    analysis_content = Column(JSON, nullable=True)

    assigned_agent_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    assigned_agent = relationship("User", back_populates="negotiations")

    email_thread_id = Column(UUID(as_uuid=True), ForeignKey("email_threads.id"))
    email_thread = relationship("EmailThread", back_populates="negotiation")

    legal_process_id = Column(
        UUID(as_uuid=True), ForeignKey("legal_processes.id"), nullable=True
    )
    legal_process = relationship("LegalProcess", back_populates="negotiations")


# --- Modelos do Departamento de E-mail (com relações adicionadas) ---
class EmailThread(Base):
    __tablename__ = "email_threads"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    conversation_id = Column(String, unique=True, index=True, nullable=False)
    subject = Column(String, index=True)
    first_email_date = Column(DateTime)
    last_email_date = Column(DateTime, index=True)
    participants = Column(JSON)

    messages = relationship(
        "EmailMessage",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="EmailMessage.sent_datetime",
    )
    analysis = relationship(
        "Analysis",
        back_populates="email_thread",
        uselist=False,
        cascade="all, delete-orphan",
    )
    negotiation = relationship(
        "Negotiation",
        back_populates="email_thread",
        uselist=False,
        cascade="all, delete-orphan",
    )
    judicial_analysis = relationship(
        "JudicialAnalysis", back_populates="thread", cascade="all, delete-orphan"
    )


class EmailMessage(Base):
    __tablename__ = "email_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    message_id = Column(String, unique=True, nullable=False)
    thread_id = Column(
        UUID(as_uuid=True), ForeignKey("email_threads.id"), nullable=False
    )
    sender = Column(String)
    body = Column(Text)
    sent_datetime = Column(DateTime, nullable=False)
    internet_message_id = Column(String, unique=True, nullable=True, index=True)
    has_attachments = Column(Boolean, default=False)
    importance = Column(String, nullable=True)

    thread = relationship("EmailThread", back_populates="messages")


# --- Modelos do Departamento de WhatsApp ---
class WhatsappConversation(Base):
    """Representa uma conversa única com um contato no WhatsApp."""

    __tablename__ = "whatsapp_conversations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    instance_name = Column(String, index=True, nullable=False)
    remote_jid = Column(String, index=True, nullable=False)
    last_message_timestamp = Column(DateTime(timezone=True), index=True, nullable=True)

    messages = relationship(
        "WhatsappMessage",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="WhatsappMessage.message_timestamp.asc()",
    )
    analysis = relationship(
        "WhatsappAnalysis",
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("instance_name", "remote_jid", name="uq_wpp_instance_jid"),
        Index("ix_wpp_conv_lastmsg", "last_message_timestamp"),
    )


class WhatsappMessage(Base):
    """Representa uma única mensagem dentro de uma conversa do WhatsApp."""

    __tablename__ = "whatsapp_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    conversation_id = Column(
        UUID(as_uuid=True), ForeignKey("whatsapp_conversations.id"), nullable=False
    )
    external_id = Column(String, index=True, nullable=False)  # ID da API de origem
    sender = Column(String, nullable=False)  # Ex: "Cliente", "Negociador"
    text = Column(Text, nullable=True)
    message_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    message_type = Column(String, nullable=True)  # Ex: "conversation", "audioMessage"

    conversation = relationship("WhatsappConversation", back_populates="messages")

    __table_args__ = (
        UniqueConstraint("conversation_id", "external_id", name="uq_wpp_conv_ext_id"),
    )


class WhatsappAnalysis(Base):
    """Armazena o resultado da análise de IA para uma conversa de WhatsApp."""

    __tablename__ = "whatsapp_analyses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    conversation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("whatsapp_conversations.id"),
        unique=True,
        index=True,
        nullable=False,
    )
    extracted_data = Column(JSON, nullable=True)
    temperature_assessment = Column(JSON, nullable=True)
    director_decision = Column(JSON, nullable=True)
    guard_report = Column(JSON, nullable=True)
    context = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), default=func.now()
    )

    conversation = relationship("WhatsappConversation", back_populates="analysis")


# --- Modelos de Análise e Chat ---
class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    email_thread_id = Column(UUID(as_uuid=True), ForeignKey("email_threads.id"))
    extracted_data = Column(JSON, nullable=True)
    temperature_assessment = Column(JSON, nullable=True)
    director_decision = Column(JSON, nullable=True)
    kpis = Column(JSON, nullable=True)
    advisor_recommendation = Column(JSON, nullable=True)
    context = Column(JSON, nullable=True)
    formal_summary = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now(), default=func.now())

    email_thread = relationship("EmailThread", back_populates="analysis")


class JudicialAnalysis(Base):
    __tablename__ = "judicial_analyses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    thread_id = Column(
        UUID(as_uuid=True), ForeignKey("email_threads.id"), nullable=False
    )
    recommended_action = Column(JSON, nullable=False)
    legal_rationale = Column(Text, nullable=False)
    conservative_thesis = Column(JSON, nullable=True)
    strategic_thesis = Column(JSON, nullable=True)
    confidence_score = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    thread = relationship("EmailThread", back_populates="judicial_analysis")


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    title = Column(String, default="Nova Conversa")
    created_at = Column(DateTime, server_default=func.now())

    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    owner = relationship("User", back_populates="chat_sessions")

    messages = relationship(
        "ChatMessage", back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())

    session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"))
    session = relationship("ChatSession", back_populates="messages")
