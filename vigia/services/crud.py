import base64
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, func
from db import models
from vigia.api import schemas
from passlib.context import CryptContext
from datetime import datetime, timezone
import dateutil.parser

# O pwd_context pode ser movido para um arquivo de utils/segurança se preferir
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password):
    return pwd_context.hash(password)

# --- User CRUD (sem alterações) ---
def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def create_user(db: Session, user: schemas.UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

# --- Negotiation CRUD (sem alterações) ---
def get_or_create_default_user(db: Session):
    """Busca ou cria um usuário padrão para ser o agente de novas negociações."""
    default_email = "agente.padrao@vigia.com"
    user = get_user_by_email(db, email=default_email)
    if not user:
        # CUIDADO: Em produção, use uma senha segura vinda de configs
        user_in = schemas.UserCreate(email=default_email, password="defaultpassword")
        user = create_user(db, user_in)
    return user


def get_negotiations(db: Session, user_id: str, skip: int = 0, limit: int = 100):
    """
    Busca todas as negociações de um usuário, incluindo os dados agregados.
    Esta query é mais simples e robusta, usando LEFT JOINs.
    """
    # Subquery para agregar dados por thread: contagem e data/corpo da última mensagem
    last_message_subquery = db.query(
        models.EmailMessage.thread_id,
        func.count(models.EmailMessage.id).label('message_count'),
        func.max(models.EmailMessage.sent_datetime).label('last_message_time')
    ).group_by(models.EmailMessage.thread_id).subquery()

    last_message_body_subquery = db.query(
        models.EmailMessage.thread_id,
        models.EmailMessage.body
    ).join(
        last_message_subquery,
        (models.EmailMessage.thread_id == last_message_subquery.c.thread_id) &
        (models.EmailMessage.sent_datetime == last_message_subquery.c.last_message_time)
    ).subquery()
    
    # Query principal que junta tudo
    results = db.query(
        models.Negotiation,
        func.coalesce(last_message_subquery.c.message_count, 0).label('message_count'),
        last_message_subquery.c.last_message_time.label('last_message_time'),
        last_message_body_subquery.c.body.label('last_message_body')
    )\
    .outerjoin(models.Negotiation.email_thread)\
    .outerjoin(last_message_subquery, models.Negotiation.email_thread_id == last_message_subquery.c.thread_id)\
    .outerjoin(last_message_body_subquery, models.Negotiation.email_thread_id == last_message_body_subquery.c.thread_id)\
    .options(joinedload(models.Negotiation.legal_process))\
    .filter(models.Negotiation.assigned_agent_id == user_id)\
    .order_by(desc('last_message_time'))\
    .offset(skip).limit(limit).all()

    return results

def get_negotiation_details(db: Session, negotiation_id: str):
    # Usar joinedload é mais eficiente para carregar relações
    return db.query(models.Negotiation).options(
        joinedload(models.Negotiation.email_thread).joinedload(models.EmailThread.messages)
    ).filter(models.Negotiation.id == negotiation_id).first()


# --- Legal Process CRUD (LÓGICA PRINCIPAL IMPLEMENTADA) ---
def get_process_by_number(db: Session, process_number: str):
    return db.query(models.LegalProcess).filter(models.LegalProcess.process_number == process_number).first()

def upsert_process_from_jusbr_data(db: Session, jusbr_data: dict, user_id: str):
    """
    Função central que atualiza ou cria um processo e suas relações
    a partir do JSON bruto do Jus.br, incluindo o conteúdo dos documentos.
    """
    process_number = jusbr_data.get("numeroProcesso")
    if not process_number:
        return None

    # 1. Encontra ou cria o processo principal (lógica de "upsert")
    process = get_process_by_number(db, process_number)
    if not process:
        process = models.LegalProcess(process_number=process_number, owner_id=user_id)
        db.add(process)

    # 2. Atualiza os dados principais do processo com extração segura
    tramitacao = jusbr_data.get("tramitacaoAtual", {})
    
    # Extração segura para evitar erros se chaves não existirem
    classe_info = tramitacao.get("classe", [{}])[0]
    assunto_info = tramitacao.get("assunto", [{}])[0]
    distribuicao_info = tramitacao.get("distribuicao", [{}])[0]
    orgao_julgador_info = distribuicao_info.get("orgaoJulgador", [{}])[0]

    process.classe_processual = classe_info.get("descricao")
    process.assunto = assunto_info.get("descricao")
    process.orgao_julgador = orgao_julgador_info.get("nome")
    process.tribunal = jusbr_data.get("siglaTribunal")
    process.valor_causa = tramitacao.get("valorAcao")
    
    if tramitacao.get("dataHoraAjuizamento"):
        process.start_date = dateutil.parser.isoparse(tramitacao["dataHoraAjuizamento"])
        
    process.last_update = datetime.now(timezone.utc)
    process.raw_data = jusbr_data # Salva o JSON bruto para referência futura

    # 3. Limpa relações antigas para sincronizar com os dados mais recentes
    # Esta é a estratégia mais simples para garantir que não haja dados duplicados ou obsoletos.
    if process.id: # Apenas se o processo já existe no banco
        db.query(models.ProcessMovement).filter(models.ProcessMovement.process_id == process.id).delete()
        db.query(models.ProcessParty).filter(models.ProcessParty.process_id == process.id).delete()
        db.query(models.ProcessDocument).filter(models.ProcessDocument.process_id == process.id).delete()

    # 4. Adiciona as novas movimentações
    for mov_data in tramitacao.get("movimentos", []):
        db_mov = models.ProcessMovement(
            date=dateutil.parser.isoparse(mov_data["dataHora"]),
            description=mov_data["descricao"],
            process=process  # Associa ao processo principal
        )
        db.add(db_mov)
        
    # 5. Adiciona as novas partes
    for party_data in tramitacao.get("partes", []):
        doc_principal = party_data.get("documentosPrincipais", [{}])[0]
        db_party = models.ProcessParty(
            polo=party_data.get("polo"),
            name=party_data.get("nome"),
            document_type=doc_principal.get("tipo"),
            document_number=doc_principal.get("numero"),
            representatives=party_data.get("representantes", []),
            process=process # Associa ao processo principal
        )
        db.add(db_party)

    # 6. Adiciona os novos documentos (obtidos pelo PjeWorker)
    # A chave 'documentos_com_conteudo' vem do resultado da sua task Celery
    for doc_data in jusbr_data.get("documentos_com_conteudo", []):
        if doc_data.get("error"): 
            continue # Pula documentos que falharam ao serem baixados

        binary_content = None
        # Decodifica o conteúdo do arquivo de Base64 para binário
        if doc_data.get("binary_content_b64"):
            binary_content = base64.b64decode(doc_data["binary_content_b64"])

        db_doc = models.ProcessDocument(
            external_id=doc_data.get("external_id"),
            name=doc_data.get("name"),
            document_type=doc_data.get("document_type"),
            juntada_date=dateutil.parser.isoparse(doc_data["juntada_date"]),
            file_type=doc_data.get("file_type"),
            file_size=doc_data.get("file_size"),
            text_content=doc_data.get("text_content"),
            binary_content=binary_content,
            process=process # Associa ao processo principal
        )
        db.add(db_doc)
        
    try:
        db.commit()
        db.refresh(process)
        return process
    except Exception as e:
        db.rollback()
        # Logar o erro aqui é uma boa prática
        print(f"Erro ao salvar no banco de dados: {e}")
        return None

def get_processes(db: Session, user_id: str, skip: int = 0, limit: int = 100):
    return db.query(models.LegalProcess)\
        .filter(models.LegalProcess.owner_id == user_id)\
        .order_by(desc(models.LegalProcess.last_update))\
        .offset(skip).limit(limit).all()

def get_process_details(db: Session, process_id: str):
    # Esta função agora é implicitamente usada pelo endpoint sync_and_get_process_details
    # pois ele retorna o objeto completo após o upsert.
    return db.query(models.LegalProcess).filter(models.LegalProcess.id == process_id).first()

# --- Chat CRUD (sem alterações) ---
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