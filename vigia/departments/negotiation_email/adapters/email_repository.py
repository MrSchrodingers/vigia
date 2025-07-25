import structlog
from typing import  Dict
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert

from db.session import SessionLocal
from db import models
from ..ports.email_repository_port import EmailRepositoryPort

logger = structlog.get_logger(__name__) 

class PostgresEmailRepository(EmailRepositoryPort):
    """Implementação do repositório de e-mail para o banco de dados PostgreSQL."""
    
    def save_threads_and_messages(self, threads_data: Dict[str, Dict]) -> int:
        db: Session = SessionLocal()
        total_messages_saved = 0
        try:
            for conv_id, data in threads_data.items():
                # Passo 1: Fazer o UPSERT da Thread para obter seu ID
                thread_stmt = insert(models.EmailThread).values(
                    conversation_id=conv_id,
                    subject=data["subject"],
                    first_email_date=data["first_email_date"],
                    last_email_date=data["last_email_date"],
                    participants=data["participants"]
                ).on_conflict_do_update(
                    index_elements=['conversation_id'],
                    set_={
                        'subject': data["subject"],
                        'last_email_date': data["last_email_date"],
                        'participants': data["participants"]
                    }
                ).returning(models.EmailThread.id)
                
                result = db.execute(thread_stmt)
                thread_id = result.scalar_one()

                # Passo 2: Preparar e inserir todas as mensagens da thread de uma vez
                messages_to_insert = []
                for email_dto in data["messages"]:
                    messages_to_insert.append({
                        "thread_id": thread_id,
                        "message_id": email_dto.id,
                        "internet_message_id": email_dto.internet_message_id,
                        "sender": email_dto.from_address,
                        "body": email_dto.body_content,
                        "sent_datetime": email_dto.sent_datetime,
                        "has_attachments": email_dto.has_attachments,
                        "importance": email_dto.importance
                    })
                
                if messages_to_insert:
                    message_stmt = insert(models.EmailMessage).values(
                        messages_to_insert
                    ).on_conflict_do_nothing(index_elements=['message_id'])
                    
                    db.execute(message_stmt)
                    total_messages_saved += len(messages_to_insert)

            db.commit()
            logger.info("repository.save_threads.success", count=len(threads_data))
            return total_messages_saved
        except Exception:
            logger.exception("repository.save_threads.error")
            db.rollback()
            return 0
        finally:
            db.close()