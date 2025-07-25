from .context_agents import EmailDataMinerAgent, ContextSynthesizerAgent
from .extraction_specialist_agents import (
    SubjectDataExtractorAgent,
    LegalFinancialSpecialistAgent,
    NegotiationStageSpecialistAgent,
)
from .extraction_manager_agent import EmailManagerAgent
from .temperature_agents import EmailBehavioralAgent
from .director_agent import EmailDirectorAgent

# --- Instâncias dos Agentes de Contexto ---
context_miner_agent = EmailDataMinerAgent()
context_synthesizer_agent = ContextSynthesizerAgent() 

# --- Instâncias dos Agentes de Extração (Especialistas e Gerente) ---
extraction_subject_agent = SubjectDataExtractorAgent()
extraction_legal_financial_agent = LegalFinancialSpecialistAgent()
extraction_stage_agent = NegotiationStageSpecialistAgent()
extraction_manager_agent = EmailManagerAgent()

# --- Instâncias dos Agentes de Temperatura ---
temperature_behavioral_agent = EmailBehavioralAgent()

# --- Instância do Agente Diretor ---
director_agent = EmailDirectorAgent()

__all__ = [
    "context_miner_agent",
    "context_synthesizer_agent",
    "extraction_subject_agent",
    "extraction_legal_financial_agent",
    "extraction_stage_agent",
    "extraction_manager_agent",
    "temperature_behavioral_agent",
    "director_agent",
]