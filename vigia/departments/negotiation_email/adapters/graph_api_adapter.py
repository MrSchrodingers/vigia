import structlog
import requests
from requests.adapters import HTTPAdapter, Retry
from datetime import datetime, timezone
from typing import Generator, List

from vigia.config import settings
from ..ports.graph_client_port import GraphClientPort
from ..dto.email_dto import FolderDTO, EmailDTO
from ..auth.token_provider import TOKEN_PROVIDER

logger = structlog.get_logger(__name__)

class GraphApiAdapter(GraphClientPort):
    """
    Adaptador de implementação para a Microsoft Graph API.
    Responsável pela comunicação HTTP, retries, paginação e conversão para DTOs.
    """
    _TIMEOUT = (5, 60)  # (connect, read)

    def __init__(self) -> None:
        self.base_url = settings.GRAPH_BASE_URL.rstrip("/")
        self.session = self._build_session()

    def fetch_mail_folders(self, account_email: str) -> List[FolderDTO]:
        log = logger.bind(account_email=account_email)
        log.info("graph_adapter.fetch_mail_folders.start")
        
        url = f"{self.base_url}/users/{account_email}/mailFolders"
        folders = [
            self._to_folder_dto(item)
            for page in self._paginate(url, log)
            for item in page.get("value", [])
        ]
        log.info("graph_adapter.fetch_mail_folders.success", total=len(folders))
        return folders

    def fetch_messages_in_folder(self, account_email: str, folder_id: str) -> List[EmailDTO]:
        log = logger.bind(account_email=account_email, folder_id=folder_id)
        log.info("graph_adapter.fetch_messages_in_folder.start")

        fields = [
            "id", "subject", "body", "sentDateTime", "isRead", "conversationId",
            "hasAttachments", "from", "toRecipients", "ccRecipients",
            "importance", "isReadReceiptRequested", "internetMessageId"
        ]
        select_query = f"$select={','.join(fields)}"
        url = (
            f"{self.base_url}/users/{account_email}/mailFolders/{folder_id}/messages"
            f"?$orderby=sentDateTime desc&{select_query}&$top=50"
        )
        emails = [
            self._to_email_dto(item)
            for page in self._paginate(url, log)
            for item in page.get("value", [])
        ]
        log.info("graph_adapter.fetch_messages_in_folder.success", total=len(emails))
        return emails

    def fetch_conversation_thread(self, account_email: str, conversation_id: str) -> List[EmailDTO]:
        log = logger.bind(account_email=account_email, conversation_id=conversation_id)
        log.info("graph_adapter.fetch_conversation_thread.start")

        fields = [
            "id", "subject", "sentDateTime", "isRead", "conversationId",
            "hasAttachments", "from", "toRecipients", "importance", 
            "isReadReceiptRequested", "internetMessageId", "body"
        ]
        select_query = f"$select={','.join(fields)}"
        url = (
            f"{self.base_url}/users/{account_email}/messages"
            f"?$filter=conversationId eq '{conversation_id}'"
            f"&$orderby=sentDateTime asc&{select_query}&$top=100"
        )
        page = self._get(url)
        emails = [self._to_email_dto(item) for item in page.get("value", [])]
        log.info("graph_adapter.fetch_conversation_thread.success", total=len(emails))
        return emails

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        retry_cfg = Retry(
            total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
        )
        session.mount("https://", HTTPAdapter(max_retries=retry_cfg))
        return session

    def _headers(self) -> dict[str, str]:
        token = TOKEN_PROVIDER.get_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _get(self, url: str) -> dict:
        try:
            resp = self.session.get(url, headers=self._headers(), timeout=self._TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException:
            logger.exception("graph_adapter.request.error", url=url)
            raise

    def _paginate(self, first_url: str, log) -> Generator[dict, None, None]:
        url = first_url
        seen_urls = {url}
        while url:
            data = self._get(url)
            yield data
            url = data.get("@odata.nextLink")
            if url in seen_urls:
                log.error("graph_adapter.pagination.loop_detected", url=url)
                break
            seen_urls.add(url)

    @staticmethod
    def _to_folder_dto(item: dict) -> FolderDTO:
        return FolderDTO(
            id=item["id"],
            display_name=item["displayName"],
            unread_count=item.get("unreadItemCount", 0),
            total_count=item.get("totalItemCount", 0),
        )

    @staticmethod
    def _to_email_dto(item: dict) -> EmailDTO:
        to_addresses = [
            r["emailAddress"]["address"]
            for r in item.get("toRecipients", []) if r.get("emailAddress", {}).get("address")
        ]
        return EmailDTO(
            id=item["id"],
            subject=item.get("subject", ""),
            body_content=item.get("body", {}).get("content", ""),
            body_content_type=item.get("body", {}).get("contentType", "text"),
            sent_datetime=datetime.fromisoformat(item["sentDateTime"].replace("Z", "+00:00")).astimezone(timezone.utc),
            conversation_id=item["conversationId"],
            from_address=item.get("from", {}).get("emailAddress", {}).get("address", ""),
            to_addresses=to_addresses,
            internet_message_id=item.get("internetMessageId"),
            has_attachments=item.get("hasAttachments", False),
            importance=item.get("importance"),
        )