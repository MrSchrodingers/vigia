import structlog
from typing import Dict
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from db.session import SessionLocal
from db import models
from vigia.services import crud
from ..ports.email_repository_port import EmailRepositoryPort

logger = structlog.get_logger(__name__)

class PostgresEmailRepository(EmailRepositoryPort):
    """Implementação do repositório de e-mail para o banco de dados PostgreSQL."""
    
    def save_threads_and_messages(self, threads_data: Dict[str, Dict]) -> int:
        db: Session = SessionLocal()
        total_messages_saved = 0
        try:
            # Garante que temos um usuário padrão para atribuir as negociações
            default_agent = crud.get_or_create_default_user(db)
            if not default_agent:
                raise Exception("Não foi possível encontrar ou criar um agente padrão.")

            for conv_id, data in threads_data.items():
                # Passo 1: Verifica se a thread já existe
                db_thread = db.query(models.EmailThread).filter_by(conversation_id=conv_id).first()

                # Normaliza participants para list (pode ter vindo como set do enrichment)
                participants = data.get("participants") or []
                if isinstance(participants, set):
                    participants = sorted(participants)

                if not db_thread:
                    # NOVA CONVERSA: cria Thread e Negociação
                    db_thread = models.EmailThread(
                        conversation_id=conv_id,
                        subject=data["subject"],
                        first_email_date=data["first_email_date"],
                        last_email_date=data["last_email_date"],
                        participants=participants,
                    )
                    db.add(db_thread)

                    db_negotiation = models.Negotiation(
                        email_thread=db_thread,
                        assigned_agent=default_agent,
                        status="active",
                        priority="medium",
                    )
                    db.add(db_negotiation)
                    logger.info("repository.new_thread_and_negotiation.created", conv_id=conv_id)
                else:
                    # THREAD EXISTENTE: atualiza campos básicos
                    db_thread.subject = data["subject"]
                    db_thread.last_email_date = data["last_email_date"]
                    db_thread.participants = participants

                db.flush()  # garante db_thread.id

                # Passo 2: Inserção em massa de mensagens (com deduplicação local)
                messages_to_insert = [
                    {
                        "thread_id": db_thread.id,
                        "message_id": email_dto.id,
                        "internet_message_id": email_dto.internet_message_id,
                        "sender": email_dto.from_address,
                        "body": email_dto.body_content,
                        "sent_datetime": email_dto.sent_datetime,
                        "has_attachments": email_dto.has_attachments,
                        "importance": email_dto.importance,
                    }
                    for email_dto in data["messages"]
                ]

                if messages_to_insert:
                    # Dedup no lote por message_id e internet_message_id
                    unique_rows, seen_msg_ids, seen_imids = [], set(), set()
                    for row in messages_to_insert:
                        mid = row["message_id"]
                        imid = row.get("internet_message_id")
                        if mid in seen_msg_ids or (imid and imid in seen_imids):
                            continue
                        seen_msg_ids.add(mid)
                        if imid:
                            seen_imids.add(imid)
                        unique_rows.append(row)

                    if unique_rows:
                        stmt = insert(models.EmailMessage).values(unique_rows)
                        # Catch-all: ignora qualquer conflito de unicidade (message_id, internet_message_id, etc.)
                        stmt = stmt.on_conflict_do_nothing().returning(models.EmailMessage.id)
                        result = db.execute(stmt)
                        inserted = len(result.scalars().all())
                        total_messages_saved += inserted

            db.commit()
            logger.info("repository.save_threads.success", count=len(threads_data))
            return total_messages_saved
        except Exception:
            logger.exception("repository.save_threads.error")
            db.rollback()
            return 0
        finally:
            db.close()
