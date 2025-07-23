from pydantic import BaseModel, Field

class SalvarDadosNegociacao(BaseModel):
    """Salva os dados extraídos de uma negociação no banco de dados do Vigia."""
    produto: str = Field(..., description="O produto ou serviço sendo negociado.")
    valor: float = Field(..., description="O valor monetário da negociação.")
    status: str = Field(..., description="O status atual da negociação, ex: 'Em Andamento', 'Acordo Fechado'.")

class CriarDealNoPipedrive(BaseModel):
    """Cria um novo 'Deal' (Negócio) no Pipedrive com base nos dados da conversa."""
    titulo_deal: str = Field(..., description="Um título claro para o deal, ex: 'Negociação com João Silva'.")
    valor_deal: float = Field(..., description="O valor monetário do deal.")
    nome_contato: str = Field(..., description="Nome da pessoa de contato no Pipedrive.")
    telefone_contato: str = Field(..., description="Telefone da pessoa de contato para buscar ou criar no Pipedrive.")

class AlertarSupervisor(BaseModel):
    """Envia uma notificação urgente para um supervisor humano."""
    motivo: str = Field(..., description="A razão específica pela qual o supervisor precisa ser alertado.")
    remote_jid: str = Field(..., description="O identificador da conversa que precisa de atenção.")