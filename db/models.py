from sqlalchemy import Column, String, DateTime, func, ForeignKey, Text, JSON, Boolean
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from lib.uuid import uuid7 as lib_uuid7

Base = declarative_base()

def as_std_uuid():
    # Converte lib_uuid.UUID → uuid.UUID
    return uuid.UUID(str(lib_uuid7()))

class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    remote_jid = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now(), default=func.now())

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")
    
    # A relação com a análise agora é polimórfica
    analysis = relationship(
        "Analysis",
        primaryjoin="and_(Conversation.id==foreign(Analysis.analysable_id), "
                    "Analysis.analysable_type=='conversation')",
        uselist=False,
        cascade="all, delete-orphan",
        overlaps="conversation,analysis"
    )

class Message(Base):
    __tablename__ = "messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    external_id = Column(String, unique=True, index=True, nullable=False)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    sender = Column(String, nullable=False)
    text = Column(Text, nullable=True)
    message_timestamp = Column(DateTime, nullable=False)
    
    conversation = relationship("Conversation", back_populates="messages")

# --- Modelos do Departamento de E-mail ---
class EmailThread(Base):
    __tablename__ = 'email_threads'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    conversation_id = Column(String, unique=True, index=True, nullable=False)
    subject = Column(String, index=True)
    first_email_date = Column(DateTime)
    last_email_date = Column(DateTime, index=True)
    participants = Column(JSON)
    
    messages = relationship("EmailMessage", back_populates="thread", cascade="all, delete-orphan")

    # A relação com a análise agora é polimórfica
    analysis = relationship(
        "Analysis",
        primaryjoin="and_(EmailThread.id==foreign(Analysis.analysable_id), "
                    "Analysis.analysable_type=='email_thread')",
        uselist=False,
        cascade="all, delete-orphan"
    )

class EmailMessage(Base):
    __tablename__ = 'email_messages'
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    message_id = Column(String, unique=True, nullable=False)
    thread_id = Column(UUID(as_uuid=True), ForeignKey('email_threads.id'), nullable=False, default=as_std_uuid)
    sender = Column(String)
    body = Column(Text)
    sent_datetime = Column(DateTime, nullable=False)
    internet_message_id = Column(String, unique=True, nullable=True, index=True)
    has_attachments = Column(Boolean, default=False)
    importance = Column(String, nullable=True) # Ex: 'normal', 'high'
    
    thread = relationship("EmailThread", back_populates="messages")


# --- Modelo de Análise Generalizado (Polimórfico) ---
class Analysis(Base):
    __tablename__ = "analyses"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    
    # Colunas para a associação polimórfica
    analysable_id = Column(String, nullable=False, index=True)
    analysable_type = Column(String(50), nullable=False)

    # Dados da Análise
    extracted_data = Column(JSON, nullable=True)
    temperature_assessment = Column(JSON, nullable=True)
    director_decision = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now(), default=func.now())

    # Se quiser, pode adaptar para funcionar com diferentes tipos de PK (UUID e Integer)
    __mapper_args__ = {
        'polymorphic_on': analysable_type
    }