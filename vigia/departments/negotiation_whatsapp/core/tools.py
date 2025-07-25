from pydantic import BaseModel, Field

class SalvarDadosNegociacao(BaseModel):
    """Salva os dados extraídos de uma negociação no banco de dados do Vigia."""
    produto: str = Field(..., description="O produto ou serviço sendo negociado.")
    valor: float = Field(..., description="O valor monetário da negociação.")
    status: str = Field(..., description="O status atual da negociação, ex: 'Em Andamento', 'Acordo Fechado'.")

class CriarAtividadeNoPipedrive(BaseModel):
    """Cria uma nova 'Activity' (Tarefa de follow-up) no Pipedrive para lembrar um operador humano de uma ação necessária."""
    subject: str = Field(..., description="O título ou assunto da atividade a ser criada. Ex: 'Follow-up sobre acordo com Marcos'.")
    due_date: str = Field(..., description="A data de vencimento para a atividade, quando a ação precisa ser tomada. Formato estrito: AAAA-MM-DD.")
    person_phone: str = Field(..., description="O número de telefone da pessoa de contato para associar a atividade.")
    note: str = Field(..., description="Um resumo conciso da conversa ou o motivo da atividade para ser adicionado como nota.")

class AlertarSupervisor(BaseModel):
    """Envia uma notificação urgente para um supervisor humano."""
    motivo: str = Field(..., description="A razão específica pela qual o supervisor precisa ser alertado.")
    remote_jid: str = Field(..., description="O identificador da conversa que precisa de atenção.")