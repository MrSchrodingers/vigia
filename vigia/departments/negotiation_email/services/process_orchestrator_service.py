from datetime import datetime, timezone
from sqlalchemy.orm import Session
from db import models
from vigia.departments.negotiation_email.agents.judicial_jury_agents import PostSentenceAgent, TransitInRemJudicatamAgent

# --- Palavras-chave para o Roteamento ---
# Casos que devem ser encerrados rapidamente sem IA
CUTOFF_KEYWORDS = [
    "audiência designada", "audiencia de conciliacao", "saneamento e organização do processo",
    "deferida a produção de prova", "perícia designada", "conclusos para despacho",
    "citação expedida", "aguardando contestação"
]

# Casos que indicam Fase Recursal
RECURSAL_KEYWORDS = [
    "apelação", "apelacao", "recurso inominado", "embargos de declaração", "agravo de instrumento",
    "recurso especial", "recurso extraordinário", "contrarrazões", "remetidos os autos para o tribunal"
]

# Casos que indicam Trânsito em Julgado
TRANSITO_KEYWORDS = [
    "trânsito em julgado", "transitou em julgado", "decurso de prazo", "certidão de decurso",
    "renúncia ao prazo", "baixa definitiva", "arquivado definitivamente", "cumprimento de sentença definitivo"
]

class ProcessStatusOrchestrator:
    def __init__(self, db_session: Session):
        self.db = db_session
        self.transit_agent = TransitInRemJudicatamAgent()
        self.post_sentence_agent = PostSentenceAgent()

    def _get_process_data(self, process: models.LegalProcess):
        """Coleta e formata os dados necessários para os agentes."""
        movements = sorted(process.movements, key=lambda m: m.date, reverse=False)
        last_50_movements = movements[-50:]
        
        movimentos_payload = [
            {"data": m.date.isoformat(), "descricao": m.description.lower()} for m in last_50_movements
        ]

        documentos_relevantes = [d for d in process.documents if d.document_type and \
            any(term in d.document_type.lower() for term in ['sentença', 'acórdão', 'decisão'])]
        
        trechos_decisoes = ""
        for doc in documentos_relevantes:
            if doc.text_content:
                trechos_decisoes += f"\n---\nDOCUMENTO: {doc.name}\nDATA: {doc.juntada_date}\nCONTEÚDO:\n{doc.text_content[:2000]}...\n---\n"
        
        return movimentos_payload, trechos_decisoes

    async def analyze(self, process: models.LegalProcess) -> dict:
        """
        Executa o fluxo de análise completo (MoE).
        """
        movimentos_payload, trechos_decisoes = self._get_process_data(process)
        all_descriptions = " ".join([m['descricao'] for m in movimentos_payload])

        # Etapa 1: Pré-Filtro Rápido (Cutoff)
        for keyword in CUTOFF_KEYWORDS:
            if keyword in all_descriptions:
                return {
                    "category": "Em Andamento",
                    "subcategory": f"Atividade de instrução recente ('{keyword}')",
                    "status": "Não Aplicável",
                    "justificativa": "Processo em fase de instrução ou movimentação inicial, análise de finalização não aplicável.",
                    "source": "Orchestrator Cutoff"
                }

        # Etapa 2: Roteamento para Especialista
        if any(keyword in all_descriptions for keyword in RECURSAL_KEYWORDS):
            print(f"Processo {process.process_number}: Roteado para Agente de Fase Recursal.")
            return await self.post_sentence_agent.execute(movimentos_payload, trechos_decisoes)

        if any(keyword in all_descriptions for keyword in TRANSITO_KEYWORDS):
            print(f"Processo {process.process_number}: Roteado para Agente de Trânsito em Julgado.")
            return await self.transit_agent.execute(movimentos_payload, trechos_decisoes)

        # Etapa 3: Heurística Temporal
        sentencas = [d for d in process.documents if d.document_type and 'sentença' in d.document_type.lower()]
        if sentencas:
            ultima_sentenca = max(sentencas, key=lambda d: d.juntada_date)
            dias_desde_sentenca = (datetime.now(timezone.utc) - ultima_sentenca.juntada_date).days
            
            if 20 <= dias_desde_sentenca <= 90: # Janela de tempo razoável
                return {
                    "category": "Trânsito em Julgado",
                    "subcategory": "Iminente por Decurso de Prazo",
                    "data_transito_julgado": "Iminente",
                    "justificativa": f"A última sentença foi proferida há {dias_desde_sentenca} dias sem movimentação de recurso aparente. O trânsito em julgado é provável por decurso de prazo.",
                    "source": "Orchestrator Heuristic"
                }

        # Etapa 4: Fallback
        return {
            "category": "Análise Inconclusiva",
            "subcategory": "Padrão não identificado",
            "data_transito_julgado": "Indeterminado",
            "justificativa": "O orquestrador não identificou um padrão claro para rotear para um agente especialista ou aplicar uma heurística.",
            "source": "Orchestrator Fallback"
        }