import base64
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from db import models
from vigia.api import schemas
from passlib.context import CryptContext
from datetime import datetime
import dateutil.parser

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

# --- User CRUD ---
def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def create_user(db: Session, user: schemas.UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# --- Negotiation CRUD ---
def get_negotiations(db: Session, user_id: str, skip: int = 0, limit: int = 100):
    # Esta query é complexa e pode ser otimizada.
    # Ela busca a última mensagem para cada negociação.
    negotiations = db.query(
        models.Negotiation,
        func.count(models.EmailMessage.id).label('message_count'),
        func.max(models.EmailMessage.sent_datetime).label('last_message_time')
    ).join(models.Negotiation.email_thread).join(models.EmailThread.messages)\
    .filter(models.Negotiation.assigned_agent_id == user_id)\
    .group_by(models.Negotiation.id)\
    .order_by(desc('last_message_time'))\
    .offset(skip).limit(limit).all()
    
    return negotiations

def get_negotiation_details(db: Session, negotiation_id: str):
    return db.query(models.Negotiation).filter(models.Negotiation.id == negotiation_id).first()

# --- Legal Process CRUD ---
def get_process_by_number(db: Session, process_number: str):
    return db.query(models.LegalProcess).filter(models.LegalProcess.process_number == process_number).first()

def upsert_process_from_jusbr_data(db: Session, jusbr_data: dict, user_id: str):
    """
    Função central que atualiza ou cria um processo e suas relações
    a partir do JSON bruto do Jus.br.
    """
    process_number = jusbr_data.get("numeroProcesso")
    if not process_number:
        return None

    # 1. Encontra ou cria o processo principal
    process = get_process_by_number(db, process_number)
    if not process:
        process = models.LegalProcess(process_number=process_number, owner_id=user_id)
        db.add(process)

    # 2. Atualiza os dados principais do processo
    tramitacao = jusbr_data.get("tramitacaoAtual", {})
    process.classe_processual = tramitacao.get("classe", [{}])[0].get("descricao")
    process.assunto = tramitacao.get("assunto", [{}])[0].get("descricao")
    process.orgao_julgador = tramitacao.get("distribuicao", [{}])[0].get("orgaoJulgador", [{}])[0].get("nome")
    process.tribunal = jusbr_data.get("siglaTribunal")
    process.valor_causa = tramitacao.get("valorAcao")
    process.start_date = dateutil.parser.isoparse(tramitacao["dataHoraAjuizamento"]) if tramitacao.get("dataHoraAjuizamento") else None
    process.last_update = datetime.now()
    process.raw_data = jusbr_data # Salva o JSON bruto

    # 3. Limpa e recria as relações para garantir consistência
    db.query(models.ProcessMovement).filter(models.ProcessMovement.process_id == process.id).delete()
    db.query(models.ProcessParty).filter(models.ProcessParty.process_id == process.id).delete()
    # Para documentos, a estratégia pode ser mais complexa (verificar por ID), mas vamos simplificar por agora
    db.query(models.ProcessDocument).filter(models.ProcessDocument.process_id == process.id).delete()
    
    # 4. Adiciona as novas movimentações
    for mov in tramitacao.get("movimentos", []):
        db_mov = models.ProcessMovement(
            process=process,
            date=dateutil.parser.isoparse(mov["dataHora"]),
            description=mov["descricao"]
        )
        db.add(db_mov)
        
    # 5. Adiciona as novas partes
    for party in tramitacao.get("partes", []):
        doc = party.get("documentosPrincipais", [{}])[0]
        db_party = models.ProcessParty(
            process=process,
            polo=party["polo"],
            name=party["nome"],
            document_type=doc.get("tipo"),
            document_number=doc.get("numero"),
            representatives=party.get("representantes", [])
        )
        db.add(db_party)

    # 6. Adiciona os novos documentos, agora com conteúdo binário
    for doc_data in jusbr_data.get("documentos_com_conteudo", []):
        if doc_data.get("error"): 
            continue # Pula documentos que falharam

        binary_content = None
        if doc_data.get("binario_b64"):
            binary_content = base64.b64decode(doc_data["binario_b64"])

        db_doc = models.ProcessDocument(
            process=process,
            external_id=doc_data.get("external_id"),
            name=doc_data.get("name"),
            document_type=doc_data.get("tipo_doc"),
            juntada_date=dateutil.parser.isoparse(doc_data["juntada_date"]),
            file_type=doc_data.get("mime_type"),
            file_size=doc_data.get("tamanho"),
            text_content=doc_data.get("text_content"),
            binary_content=binary_content
        )
        db.add(db_doc)
        
    db.commit()
    db.refresh(process)
    return process

def get_processes(db: Session, user_id: str, skip: int = 0, limit: int = 100):
    return db.query(models.LegalProcess)\
        .filter(models.LegalProcess.owner_id == user_id)\
        .order_by(desc(models.LegalProcess.last_update))\
        .offset(skip).limit(limit).all()

def get_process_details(db: Session, process_id: str):
    return db.query(models.LegalProcess).filter(models.LegalProcess.id == process_id).first()

# --- Chat CRUD ---
def get_chat_session(db: Session, session_id: str, user_id: str):
    return db.query(models.ChatSession)\
        .filter(models.ChatSession.id == session_id, models.ChatSession.owner_id == user_id)\
        .first()

def create_chat_message(db: Session, message: schemas.ChatMessageCreate, session_id: str, role: str):
    db_message = models.ChatMessage(**message.dict(), session_id=session_id, role=role)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message