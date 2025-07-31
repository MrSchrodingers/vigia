from pydantic import BaseModel, Field
from typing import Literal

class CriarNotaNoPipedrive(BaseModel):
    """Cria uma nova 'Note' no Pipedrive associada a um 'Deal' existente."""
    deal_id: int = Field(..., description="O ID numérico do Deal ao qual a nota deve ser anexada.")
    content: str = Field(..., description="O conteúdo da nota, que pode ser um resumo da análise ou da negociação.")

class AgendarFollowUp(BaseModel):
    """
    Agenda uma atividade de acompanhamento (follow-up) no Pipedrive.
    Use esta ferramenta quando uma negociação está parada, aguardando resposta por muito tempo,
    ou quando uma proposta tem um prazo de validade que precisa ser monitorado.
    """
    due_date: str = Field(
        ..., 
        description="A data de vencimento para a atividade de follow-up. Formato estrito: AAAA-MM-DD."
    )
    subject: str = Field(
        ..., 
        description="O título da atividade, que deve ser claro e informativo. Ex: 'Acompanhar proposta enviada para o processo X'."
    )
    note: str = Field(
        ..., 
        description="A justificativa para o follow-up. Explique por que esta atividade é necessária com base no contexto da negociação."
    )

class AlertarSupervisorParaAtualizacao(BaseModel):
    """
    Cria uma atividade de alta prioridade para um supervisor revisar e atualizar um negócio no Pipedrive.
    Use esta ferramenta quando houver uma clara divergência entre o estado real da negociação (ex: uma contraproposta foi recebida)
    e os dados registrados no Pipedrive (ex: o estágio do negócio ainda é 'Proposta Inicial').
    """
    due_date: str = Field(
        ..., 
        description="A data de vencimento para a atividade do supervisor. Geralmente, deve ser para hoje ou amanhã. Formato estrito: AAAA-MM-DD."
    )
    motivo: str = Field(
        ..., 
        description="Descrição clara da inconsistência encontrada entre a conversa e os dados do Pipedrive que requer atenção do supervisor."
    )
    urgencia: Literal['Alta', 'Média'] = Field(
        ..., 
        description="O nível de urgência da tarefa de atualização."
    )