import base64
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import dateutil.parser
from passlib.context import CryptContext
from sqlalchemy import desc, func
from sqlalchemy.orm import Session, joinedload

from db import models
from vigia.api import schemas

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

_CNJ_RE = re.compile(r"\D+")


def _cnj_digits(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    digits = _CNJ_RE.sub("", s)
    return digits if len(digits) == 20 else None


def _format_cnj(s: Optional[str]) -> Optional[str]:
    digits = _cnj_digits(s)
    if not digits:
        return s
    return f"{digits[0:7]}-{digits[7:9]}.{digits[9:13]}.{digits[13]}.{digits[14:16]}.{digits[16:20]}"


def _set_if_present(obj: Any, attr: str, value: Any) -> None:
    if value is not None:
        setattr(obj, attr, value)


def _parse_iso_dt(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        return dateutil.parser.isoparse(v)
    except (ValueError, TypeError):
        return None


def get_password_hash(password):
    return pwd_context.hash(password)


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def create_user(db: Session, user: schemas.UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = models.User(email=user.email, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_or_create_default_user(db: Session):
    default_email = "agente.padrao@vigia.com"
    user = get_user_by_email(db, email=default_email)
    if not user:
        user_in = schemas.UserCreate(email=default_email, password="defaultpassword")
        user = create_user(db, user_in)
    return user


def get_negotiations(db: Session, user_id: str, skip: int = 0, limit: int = 100):
    user_uuid = uuid.UUID(str(user_id))

    last_message_sq = (
        db.query(
            models.EmailMessage.thread_id.label("thread_id"),
            func.count(models.EmailMessage.id).label("message_count"),
            func.max(models.EmailMessage.sent_datetime).label("last_message_time"),
        )
        .group_by(models.EmailMessage.thread_id)
        .subquery("last_msg")
    )

    last_body_sq = (
        db.query(
            models.EmailMessage.thread_id.label("thread_id"),
            models.EmailMessage.body.label("body"),
            models.EmailMessage.sent_datetime.label("sent_datetime"),
        )
        .join(
            last_message_sq,
            (models.EmailMessage.thread_id == last_message_sq.c.thread_id)
            & (
                models.EmailMessage.sent_datetime == last_message_sq.c.last_message_time
            ),
        )
        .subquery("last_body")
    )

    results = (
        db.query(
            models.Negotiation,
            func.coalesce(last_message_sq.c.message_count, 0).label("message_count"),
            last_message_sq.c.last_message_time.label("last_message_time"),
            last_body_sq.c.body.label("last_message_body"),
        )
        .outerjoin(
            models.EmailThread,
            models.Negotiation.email_thread_id == models.EmailThread.id,
        )
        .outerjoin(
            last_message_sq,
            models.Negotiation.email_thread_id == last_message_sq.c.thread_id,
        )
        .outerjoin(
            last_body_sq, models.Negotiation.email_thread_id == last_body_sq.c.thread_id
        )
        .options(joinedload(models.Negotiation.legal_process))
        .order_by(last_message_sq.c.last_message_time.desc().nullslast())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return results


def get_negotiation_details(db: Session, negotiation_id: str):
    return (
        db.query(models.Negotiation)
        .options(
            joinedload(models.Negotiation.email_thread).joinedload(
                models.EmailThread.messages
            )
        )
        .filter(models.Negotiation.id == negotiation_id)
        .first()
    )


def get_process_by_number(db: Session, process_number: str):
    digits = _cnj_digits(process_number)
    if not digits:
        return None
    return (
        db.query(models.LegalProcess)
        .filter(models.LegalProcess.process_number == digits)
        .first()
    )


def upsert_process_from_jusbr_data(
    db: Session, jusbr_data: dict, user_id: str
) -> Optional[models.LegalProcess]:
    if not jusbr_data or jusbr_data.get("erro"):
        logger.warning(
            "Payload vazio ou com erro ao tentar upsert do processo: %s", jusbr_data
        )
        return None

    numero_unico_incidencia = jusbr_data.get("numero_unico_incidencia")
    cnj_principal = _cnj_digits(jusbr_data.get("numeroProcesso"))
    cnj_formatado = _format_cnj(cnj_principal)

    process = None
    if numero_unico_incidencia:
        process = (
            db.query(models.LegalProcess)
            .filter(
                models.LegalProcess.numero_unico_incidencia == numero_unico_incidencia
            )
            .first()
        )

    if not process and cnj_formatado:
        process = (
            db.query(models.LegalProcess)
            .filter(
                models.LegalProcess.process_number == cnj_formatado,
                models.LegalProcess.numero_unico_incidencia.is_(None),
            )
            .first()
        )

    created = False
    if not process:
        if not cnj_principal:
            logger.error(
                "Não foi possível criar processo, falta CNJ principal no payload do Jus.br."
            )
            return None
        process = models.LegalProcess(
            process_number=cnj_formatado,
            numero_unico_incidencia=numero_unico_incidencia,
            owner_id=user_id,
        )
        db.add(process)
        created = True

    tramitacao = jusbr_data.get("tramitacaoAtual") or {}
    classe_info = (tramitacao.get("classe") or [{}])[0] or {}
    assunto_info = (tramitacao.get("assunto") or [{}])[0] or {}
    grau_info = tramitacao.get("grau") or {}
    tribunal_info = tramitacao.get("tribunal") or {}

    process.process_number = cnj_formatado
    _set_if_present(process, "numero_unico_incidencia", numero_unico_incidencia)
    _set_if_present(process, "grupo_incidencia", jusbr_data.get("grupo_incidencia"))
    _set_if_present(process, "valor_causa", tramitacao.get("valorAcao"))
    _set_if_present(process, "classe_processual", classe_info.get("descricao"))
    _set_if_present(process, "assunto", assunto_info.get("descricao"))

    ajuiz = _parse_iso_dt(tramitacao.get("dataHoraAjuizamento"))
    if ajuiz:
        process.start_date = ajuiz

    _set_if_present(process, "secrecy_level", jusbr_data.get("nivelSigilo"))
    _set_if_present(process, "permite_peticionar", tramitacao.get("permitePeticionar"))
    _set_if_present(
        process, "fonte_dados_codex_id", tramitacao.get("idFonteDadosCodex")
    )
    _set_if_present(process, "ativo", tramitacao.get("ativo"))

    if tramitacao.get("ativo") is not None:
        process.status = "Ativo" if tramitacao.get("ativo") else "Arquivado"

    tribunal_sigla = tribunal_info.get("sigla") or jusbr_data.get("siglaTribunal")
    _set_if_present(process, "tribunal", tribunal_sigla)
    _set_if_present(
        process, "tribunal_nome", tribunal_info.get("nome") or tribunal_sigla
    )
    _set_if_present(process, "tribunal_segmento", tribunal_info.get("segmento"))
    _set_if_present(process, "tribunal_jtr", tribunal_info.get("jtr"))

    _set_if_present(process, "instance", tramitacao.get("instancia"))
    _set_if_present(process, "degree_sigla", grau_info.get("sigla"))
    _set_if_present(process, "degree_nome", grau_info.get("nome"))
    _set_if_present(process, "degree_numero", grau_info.get("numero"))

    _set_if_present(process, "classe_codigo", classe_info.get("codigo"))
    _set_if_present(process, "assunto_codigo", assunto_info.get("codigo"))
    _set_if_present(process, "assunto_hierarquia", assunto_info.get("hierarquia"))

    process.last_update = datetime.now(timezone.utc)
    _set_if_present(process, "raw_data", jusbr_data)

    if process.id:
        db.query(models.ProcessMovement).filter_by(process_id=process.id).delete()
        db.query(models.ProcessParty).filter_by(process_id=process.id).delete()
        db.query(models.ProcessDocument).filter_by(process_id=process.id).delete()
        db.query(models.ProcessDistribution).filter_by(process_id=process.id).delete()

    for mov in tramitacao.get("movimentos") or []:
        mov_date = _parse_iso_dt(mov.get("dataHora"))
        if mov_date:
            db.add(
                models.ProcessMovement(
                    date=mov_date,
                    description=mov.get("descricao") or "",
                    process=process,
                )
            )

    for party_data in tramitacao.get("partes") or []:
        main_doc = (party_data.get("documentosPrincipais") or [{}])[0] or {}
        db.add(
            models.ProcessParty(
                polo=party_data.get("polo"),
                name=party_data.get("nome"),
                document_type=main_doc.get("tipo"),
                document_number=str(main_doc.get("numero") or ""),
                representatives=party_data.get("representantes"),
                ajg=party_data.get("assistenciaJudiciariaGratuita"),
                sigilosa=party_data.get("sigilosa"),
                process=process,
            )
        )

    for doc_meta in tramitacao.get("documentos") or []:
        juntada_date = _parse_iso_dt(doc_meta.get("dataHoraJuntada"))
        if juntada_date:
            tipo_info = doc_meta.get("tipo") or {}
            arquivo_info = doc_meta.get("arquivo") or {}
            db.add(
                models.ProcessDocument(
                    external_id=doc_meta.get("idOrigem")
                    or str(doc_meta.get("idCodex") or ""),
                    name=doc_meta.get("nome"),
                    document_type=tipo_info.get("nome"),
                    juntada_date=juntada_date,
                    sequence=doc_meta.get("sequencia"),
                    codex_id=str(doc_meta.get("idCodex") or ""),
                    href_binary=doc_meta.get("hrefBinario"),
                    file_type=arquivo_info.get("tipo"),
                    file_size=arquivo_info.get("tamanho"),
                    process=process,
                )
            )

    db.flush()

    for doc_content in jusbr_data.get("documentos_com_conteudo") or []:
        ext_id = doc_content.get("external_id")
        if doc_content.get("error") or not ext_id:
            continue

        doc_record = (
            db.query(models.ProcessDocument)
            .filter_by(process_id=process.id, external_id=ext_id)
            .first()
        )
        if doc_record:
            _set_if_present(doc_record, "text_content", doc_content.get("text_content"))
            b64 = doc_content.get("binary_content_b64")
            if b64:
                try:
                    doc_record.binary_content = base64.b64decode(b64)
                except Exception as e:
                    logger.debug(f"Falha ao decodificar binário do doc {ext_id}: {e}")

    try:
        db.commit()
        db.refresh(process)
        logger.info(
            "LegalProcess %s (instância=%s, cnj=%s).",
            "criado" if created else "atualizado",
            numero_unico_incidencia,
            cnj_principal,
        )
        return process
    except Exception as e:
        db.rollback()
        logger.exception(
            "Erro ao salvar no banco para instância %s: %s", numero_unico_incidencia, e
        )
        raise


def get_processes(db: Session, user_id: str, skip: int = 0, limit: int = 100):
    return (
        db.query(models.LegalProcess)
        .filter(models.LegalProcess.owner_id == user_id)
        .order_by(desc(models.LegalProcess.last_update))
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_process_details(db: Session, process_id: str):
    return (
        db.query(models.LegalProcess)
        .filter(models.LegalProcess.id == process_id)
        .first()
    )


def get_chat_session(db: Session, session_id: str, user_id: str):
    return (
        db.query(models.ChatSession)
        .filter(
            models.ChatSession.id == session_id, models.ChatSession.owner_id == user_id
        )
        .first()
    )


def create_chat_message(
    db: Session, message: schemas.ChatMessageCreate, session_id: str, role: str
):
    db_message = models.ChatMessage(**message.dict(), session_id=session_id, role=role)
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    return db_message
