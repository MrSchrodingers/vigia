# vigia/departments/negotiation_email/dto/email_dto.py

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

@dataclass(frozen=True)
class FolderDTO:
    id: str
    display_name: str
    unread_count: int
    total_count: int

@dataclass(frozen=True)
class EmailDTO:
    id: str
    conversation_id: str
    internet_message_id: Optional[str]
    subject: str
    body_content: str
    body_content_type: str # "html" ou "text"
    sent_datetime: datetime
    from_address: str
    to_addresses: List[str]
    has_attachments: bool
    importance: Optional[str]