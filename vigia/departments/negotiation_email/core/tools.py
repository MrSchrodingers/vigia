from pydantic import BaseModel, Field

class CriarNotaNoPipedrive(BaseModel):
    """Cria uma nova 'Note' no Pipedrive associada a um 'Deal' existente."""
    deal_id: int = Field(..., description="O ID numérico do Deal ao qual a nota deve ser anexada.")
    content: str = Field(..., description="O conteúdo da nota, que pode ser um resumo da análise ou da negociação.")