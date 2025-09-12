import base64
import uuid
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
    Busca negociações do agente com agregados de e-mail:
      - message_count (contagem de mensagens no thread)
      - last_message_time (data/hora da última mensagem)
      - last_message_body (corpo da última mensagem)
    Mantém negociações sem e-mail (count=0) graças aos LEFT JOINs.
    """
    # Garante tipo correto no filtro (UUID)
    user_uuid = uuid.UUID(str(user_id))

    # Subquery: por thread -> contagem e última data
    last_message_sq = (
        db.query(
            models.EmailMessage.thread_id.label("thread_id"),
            func.count(models.EmailMessage.id).label("message_count"),
            func.max(models.EmailMessage.sent_datetime).label("last_message_time"),
        )
        .group_by(models.EmailMessage.thread_id)
        .subquery("last_msg")
    )

    # Subquery: corpo da última mensagem (joinando na última data)
    last_body_sq = (
        db.query(
            models.EmailMessage.thread_id.label("thread_id"),
            models.EmailMessage.body.label("body"),
            models.EmailMessage.sent_datetime.label("sent_datetime"),
        )
        .join(
            last_message_sq,
            (models.EmailMessage.thread_id == last_message_sq.c.thread_id)
            & (models.EmailMessage.sent_datetime == last_message_sq.c.last_message_time),
        )
        .subquery("last_body")
    )

    # Query principal
    results = (
        db.query(
            models.Negotiation,
            func.coalesce(last_message_sq.c.message_count, 0).label("message_count"),
            last_message_sq.c.last_message_time.label("last_message_time"),
            last_body_sq.c.body.label("last_message_body"),
        )
        # LEFT JOIN explícito com EmailThread (evita ambiguidades)
        .outerjoin(models.EmailThread, models.Negotiation.email_thread_id == models.EmailThread.id)
        # LEFT JOINs com as subqueries de agregação
        .outerjoin(last_message_sq, models.Negotiation.email_thread_id == last_message_sq.c.thread_id)
        .outerjoin(last_body_sq, models.Negotiation.email_thread_id == last_body_sq.c.thread_id)
        # Carrega o processo (e você pode adicionar joinedload(Negotiation.email_thread) se quiser)
        .options(joinedload(models.Negotiation.legal_process))
        # Ordena por última mensagem, empurrando NULLs para o fim
        .order_by(last_message_sq.c.last_message_time.desc().nullslast())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return results


def get_negotiation_details(db: Session, negotiation_id: str):
    # Usar joinedload é mais eficiente para carregar relações
    return db.query(models.Negotiation).options(
        joinedload(models.Negotiation.email_thread).joinedload(models.EmailThread.messages)
    ).filter(models.Negotiation.id == negotiation_id).first()


# --- Legal Process CRUD (LÓGICA PRINCIPAL IMPLEMENTADA) ---
def get_process_by_number(db: Session, process_number: str):
    return db.query(models.LegalProcess).filter(models.LegalProcess.process_number == process_number).first()

def upsert_process_from_jusbr_data(db: Session, jusbr_data: dict, user_id: str) -> models.LegalProcess:
    """
    Atualiza ou cria uma INSTÂNCIA de processo e suas relações a partir do JSON do Jus.br.
    - Utiliza 'numero_unico_incidencia' como chave de busca para diferenciar instâncias.
    - Salva 'grupo_incidencia' para agrupar instâncias relacionadas.
    - Realiza uma sincronização completa (delete-then-create) para as relações
      (movimentos, partes, documentos) para garantir consistência.
    """
    if not jusbr_data or jusbr_data.get("erro"):
        return None

    # <-- ALTERADO: Usa o novo identificador único como chave principal para o upsert.
    numero_unico = jusbr_data.get("numero_unico_incidencia")
    if not numero_unico:
        # Fallback para o caso de um processo simples, sem múltiplas instâncias.
        numero_unico = "".join(filter(str.isdigit, jusbr_data.get("numeroProcesso", "")))

    if not numero_unico:
        print("Erro: Payload do Jus.br sem numeroProcesso ou numero_unico_incidencia.")
        return None

    # 1) Localiza ou cria a instância do processo
    process = db.query(models.LegalProcess).filter(
        models.LegalProcess.numero_unico_incidencia == numero_unico
    ).first()

    if not process:
        process = models.LegalProcess(
            numero_unico_incidencia=numero_unico,
            owner_id=user_id
        )
        db.add(process)

    # 2) Extrai dados do payload (a lógica do worker já garante que 'tramitacaoAtual' é a correta para esta instância)
    tramitacao = jusbr_data.get("tramitacaoAtual", {}) or {}
    classe_info = (tramitacao.get("classe") or [{}])[0] or {}
    assunto_info = (tramitacao.get("assunto") or [{}])[0] or {}
    distribuicoes = tramitacao.get("distribuicao") or tramitacao.get("distribuicoes") or []
    grau_info = tramitacao.get("grau", {}) or {}
    tribunal_info = jusbr_data.get("tribunal", {}) or {}

    # 3) Preenche os dados da instância do processo
    process.process_number = jusbr_data.get("numeroProcesso")
    process.grupo_incidencia = jusbr_data.get("grupo_incidencia") # <-- NOVO: Salva a flag de agrupamento
    process.valor_causa = tramitacao.get("valorAcao")
    process.classe_processual = classe_info.get("descricao")
    process.assunto = assunto_info.get("descricao")
    
    if tramitacao.get("dataHoraAjuizamento"):
        try:
            process.start_date = dateutil.parser.isoparse(tramitacao["dataHoraAjuizamento"])
        except (ValueError, TypeError):
            process.start_date = None

    # Mapeamento de campos adicionais
    process.secrecy_level = jusbr_data.get("nivelSigilo")
    process.permite_peticionar = jusbr_data.get("permitePeticionar")
    process.fonte_dados_codex_id = jusbr_data.get("idFonteDadosCodex")
    process.ativo = jusbr_data.get("ativo")
    process.status = "active" if process.ativo else "inactive"
    
    # Detalhes do Tribunal
    process.tribunal = tribunal_info.get("sigla") or jusbr_data.get("siglaTribunal")
    process.tribunal_nome = tribunal_info.get("nome") or process.tribunal
    process.tribunal_segmento = tribunal_info.get("segmento")
    process.tribunal_jtr = tribunal_info.get("jtr")

    # Grau e Instância da tramitação específica
    process.instance = tramitacao.get("instancia")
    process.degree_sigla = grau_info.get("sigla")
    process.degree_nome = grau_info.get("nome")
    process.degree_numero = grau_info.get("numero")

    # Códigos e Hierarquia
    process.classe_codigo = classe_info.get("codigo")
    process.assunto_codigo = assunto_info.get("codigo")
    process.assunto_hierarquia = assunto_info.get("hierarquia")

    # Atualiza data e armazena o JSON bruto
    process.last_update = datetime.now(timezone.utc)
    process.raw_data = jusbr_data

    # 4) Limpa relações antigas para garantir sincronização completa
    if process.id:
        # Usamos 'process.id' para garantir que estamos limpando as relações da instância correta
        db.query(models.ProcessMovement).filter(models.ProcessMovement.process_id == process.id).delete()
        db.query(models.ProcessParty).filter(models.ProcessParty.process_id == process.id).delete()
        db.query(models.ProcessDocument).filter(models.ProcessDocument.process_id == process.id).delete()
        if hasattr(models, "ProcessDistribution"):
            db.query(models.ProcessDistribution).filter(models.ProcessDistribution.process_id == process.id).delete()

    # 5) Cria novas movimentações (a partir da tramitação específica)
    for mov in tramitacao.get("movimentos", []) or []:
        try:
            mov_date = dateutil.parser.isoparse(mov["dataHora"])
            db.add(models.ProcessMovement(
                date=mov_date,
                description=mov.get("descricao", ""),
                process=process
            ))
        except (ValueError, TypeError, KeyError):
            continue

    # 6) Cria novas partes (a partir da tramitação específica)
    for party_data in tramitacao.get("partes", []) or []:
        main_doc = (party_data.get("documentosPrincipais") or [{}])[0]
        db_party = models.ProcessParty(
            polo=party_data.get("polo"),
            name=party_data.get("nome"),
            document_type=main_doc.get("tipo"),
            document_number=str(main_doc.get("numero", "")),
            representatives=party_data.get("representantes"),
            ajg=party_data.get("assistenciaJudiciariaGratuita"),
            sigilosa=party_data.get("sigilosa"),
            process=process
        )
        db.add(db_party)

    # 7) Cria metadados dos documentos (a lista de documentos é comum a todas as instâncias)
    # A lógica de anexar conteúdo binário/texto virá depois.
    documentos_metadados = tramitacao.get("documentos", []) or []
    for doc_meta in documentos_metadados:
        try:
            juntada_date = dateutil.parser.isoparse(doc_meta["dataHoraJuntada"])
            tipo_info = doc_meta.get("tipo", {})
            arquivo_info = doc_meta.get("arquivo", {})
            db.add(models.ProcessDocument(
                external_id=doc_meta.get("idOrigem") or str(doc_meta.get("idCodex", "")),
                name=doc_meta.get("nome"),
                document_type=tipo_info.get("nome"),
                juntada_date=juntada_date,
                sequence=doc_meta.get("sequencia"),
                codex_id=str(doc_meta.get("idCodex", "")),
                href_binary=doc_meta.get("hrefBinario"),
                file_type=arquivo_info.get("tipo"),
                file_size=arquivo_info.get("tamanho"),
                process=process
            ))
        except (ValueError, TypeError, KeyError):
            continue

    # Faz um flush para que os documentos recém-criados tenham um ID
    db.flush()

    # 8) Anexa o conteúdo (texto e binário) aos documentos correspondentes
    documentos_com_conteudo = jusbr_data.get("documentos_com_conteudo", []) or []
    for doc_content in documentos_com_conteudo:
        if doc_content.get("error"):
            continue
        
        # Encontra o documento correspondente que já foi criado com os metadados
        doc_record = db.query(models.ProcessDocument).filter(
            models.ProcessDocument.process_id == process.id,
            models.ProcessDocument.external_id == doc_content.get("external_id")
        ).first()

        if doc_record:
            doc_record.text_content = doc_content.get("text_content")
            if doc_content.get("binary_content_b64"):
                doc_record.binary_content = base64.b64decode(doc_content["binary_content_b64"])

    # 9) Finaliza a transação
    try:
        db.commit()
        db.refresh(process)
        return process
    except Exception as e:
        db.rollback()
        print(f"Erro ao salvar no banco de dados para {numero_unico}: {e}")
        raise

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