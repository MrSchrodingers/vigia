from abc import ABC, abstractmethod
from typing import List
from ..dto.email_dto import EmailDTO

class EmailRepositoryPort(ABC):
    """Interface (Port) que define os métodos para persistir dados de e-mail."""
    @abstractmethod
    def save_threads_and_messages(self, emails: List[EmailDTO]) -> int:
        """
        Salva uma lista de DTOs de e-mail no banco de dados.
        Retorna o número de registros salvos/atualizados.
        """
        pass