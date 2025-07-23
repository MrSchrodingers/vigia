from sqlalchemy import Column, String, DateTime, func, ForeignKey, Text, JSON
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
    updated_at = Column(DateTime, onupdate=func.now())

    messages = relationship("Message", back_populates="conversation")
    analysis = relationship("Analysis", back_populates="conversation", uselist=False)

class Message(Base):
    __tablename__ = "messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid) 
    external_id = Column(String, unique=True, index=True, nullable=False) 
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    sender = Column(String, nullable=False) # "Cliente" ou "Negociador"
    text = Column(Text, nullable=True)
    message_timestamp = Column(DateTime, nullable=False)
    
    conversation = relationship("Conversation", back_populates="messages")

class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=as_std_uuid)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id"), unique=True, nullable=False)
    extracted_data = Column(JSON, nullable=True)
    temperature_assessment = Column(JSON, nullable=True)
    director_decision = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    conversation = relationship("Conversation", back_populates="analysis")