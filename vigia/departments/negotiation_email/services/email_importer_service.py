import structlog
from typing import List, Optional, Dict
from collections import defaultdict

from vigia.config import settings
from ..ports.graph_client_port import GraphClientPort
from ..ports.email_repository_port import EmailRepositoryPort
from ..dto.email_dto import EmailDTO, FolderDTO

logger = structlog.get_logger(__name__)

class EmailImporterService:
    """
    Serviço de domínio responsável por importar e-mails, processá-los em threads
    e persisti-los no banco de dados do VigIA.
    """
    def __init__(
        self,
        graph_client: GraphClientPort,
        email_repo: EmailRepositoryPort,
    ) -> None:
        self.graph_client = graph_client
        self.email_repo = email_repo
        self.sent_folder_name = settings.SENT_FOLDER_NAME.lower()

    def run_import_for_all_accounts(self):
        """Ponto de entrada principal para a importação."""
        log = logger.bind(service="EmailImporterService")
        log.info("service.run_import.start")
        for account_email in settings.EMAIL_ACCOUNTS:
            try:
                self.import_emails_for_account(account_email)
            except Exception:
                log.exception("service.import_for_account.failed", account_email=account_email)
        log.info("service.run_import.finish")

    def import_emails_for_account(self, account_email: str):
        log = logger.bind(account_email=account_email)
        log.info("service.account.start_processing")

        folders = self.graph_client.fetch_mail_folders(account_email)
        sent_folder = self._find_sent_folder(folders)
        if not sent_folder:
            log.warning("service.sent_folder.not_found")
            return

        sent_emails = self.graph_client.fetch_messages_in_folder(
            account_email=account_email, folder_id=sent_folder.id
        )

        relevant_emails = self._filter_relevant_emails(sent_emails)
        log.info("service.emails.filtered", initial=len(sent_emails), relevant=len(relevant_emails))

        if not relevant_emails:
            return

        # CORREÇÃO: Agrupar e processar os dados da thread ANTES de salvar
        threads_data = self._process_emails_into_threads(relevant_emails)

        if threads_data:
            saved_count = self.email_repo.save_threads_and_messages(threads_data)
            log.info("service.emails.persisted", saved_threads=len(threads_data), saved_messages=saved_count)
        
        log.info("service.account.finish_processing")
    
    def _find_sent_folder(self, folders: List[FolderDTO]) -> Optional[FolderDTO]:
        return next(
            (f for f in folders if f.display_name.lower() == self.sent_folder_name),
            None,
        )

    def _filter_relevant_emails(self, emails: List[EmailDTO]) -> List[EmailDTO]:
        """Aplica as regras de negócio para filtrar e-mails que devem ser analisados."""
        filtered_by_subject = [
            email for email in emails
            if any(expr.lower() in (email.subject or "").lower() for expr in settings.SUBJECT_FILTER)
        ]
        
        final_list = []
        for email in filtered_by_subject:
            recipients_str = " ".join(email.to_addresses).lower()
            if not any(pattern.lower() in recipients_str for pattern in settings.IGNORED_RECIPIENT_PATTERNS):
                final_list.append(email)
        return final_list

    def _process_emails_into_threads(self, emails: List[EmailDTO]) -> Dict[str, Dict]:
        """Agrega uma lista de e-mails em um dicionário estruturado por thread."""
        threads = defaultdict(lambda: {
            "messages": [],
            "participants": set(),
            "dates": []
        })
        for email in emails:
            threads[email.conversation_id]["messages"].append(email)
            threads[email.conversation_id]["participants"].add(email.from_address)
            threads[email.conversation_id]["participants"].update(email.to_addresses)
            threads[email.conversation_id]["dates"].append(email.sent_datetime)

        processed_threads = {}
        for conv_id, data in threads.items():
            first_message = min(data["messages"], key=lambda m: m.sent_datetime)
            processed_threads[conv_id] = {
                "subject": first_message.subject,
                "first_email_date": min(data["dates"]),
                "last_email_date": max(data["dates"]),
                "participants": list(filter(None, data["participants"])),
                "messages": data["messages"]
            }
        return processed_threads