from abc import ABC, abstractmethod
from typing import List
from ..dto.email_dto import EmailDTO, FolderDTO

class GraphClientPort(ABC):
    """
    Interface (Port) que define os métodos para interagir com a Microsoft Graph API.
    Abstrai a fonte de dados, permitindo que a implementação seja trocada.
    """
    @abstractmethod
    def fetch_mail_folders(self, account_email: str) -> List[FolderDTO]:
        """Busca todas as pastas de e-mail de uma conta."""
        pass

    @abstractmethod
    def fetch_messages_in_folder(self, account_email: str, folder_id: str) -> List[EmailDTO]:
        """Busca todas as mensagens dentro de uma pasta específica."""
        pass

    @abstractmethod
    def fetch_conversation_thread(self, account_email: str, conversation_id: str) -> List[EmailDTO]:
        """Busca todas as mensagens de uma thread de conversa específica."""
        pass