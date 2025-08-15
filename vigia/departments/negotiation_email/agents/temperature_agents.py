import json
from typing import Dict, Any
from vigia.services import llm_service

class EmailBehavioralAgent:
    """Analisa os METADADOS da thread de e-mail para inferir o comportamento da negociação."""
    def __init__(self):
        self.system_prompt = """
        Você é um analista de metadados de comunicação. Analise o JSON de metadados de uma thread de e-mail e infira o comportamento.
        Considere os campos:
        - `importance`: "high" indica urgência.
        - `has_attachments`: `true` pode significar avanço na negociação.
        - `reply_latency_sec`: Latências baixas indicam alto engajamento; altas indicam baixo interesse.
        - `is_read_receipt_requested`: `true` pode indicar formalidade ou desconfiança.

        Crie um objeto JSON com scores de "engajamento" (0 a 10) e "urgencia" (0 a 10), e um "resumo_comportamental" em texto.
        Retorne APENAS o objeto JSON.
        """
    async def execute(self, metadata_json: Dict[str, Any]) -> str:
        metadata_str = json.dumps(metadata_json, indent=2)
        return await llm_service.llm_call(self.system_prompt, metadata_str)