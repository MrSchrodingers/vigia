# --- Agentes de Contexto ---
from .context_agents import EmailDataMinerAgent, ContextSynthesizerAgent

# --- Agentes Especialistas de Extração ---
from .extraction_specialist_agents import (
    SubjectDataExtractorAgent,
    LegalFinancialSpecialistAgent,
    NegotiationStageSpecialistAgent,
    EmailBehavioralAgent,
)
from .extraction_adversarial_agents import ExtractionValidatorAgent, ExtractionRefinerAgent

# --- Manager e Diretor ---
from .extraction_manager_agent import EmailManagerAgent
from .director_agent import EmailDirectorAgent

# --- Sumarizador ---
from .formal_summarizer_agent import FormalSummarizerAgent

# --- Juri ---
from .legal_context_agent import LegalContextSynthesizerAgent
from ..agents.judicial_jury_agents import (
    ConservativeAdvocateAgent,
    StrategicAdvocateAgent,
    JudicialArbiterAgent
)

# --- Instâncias dos Agentes de Contexto ---
context_miner_agent = EmailDataMinerAgent()
context_synthesizer_agent = ContextSynthesizerAgent()

# --- Instâncias dos Agentes de Extração (Especialistas e Gerente) ---
extraction_subject_agent = SubjectDataExtractorAgent()
extraction_legal_financial_agent = LegalFinancialSpecialistAgent()
extraction_stage_agent = NegotiationStageSpecialistAgent()
extraction_manager_agent = EmailManagerAgent()
validator_agent = ExtractionValidatorAgent()
refiner_agent = ExtractionRefinerAgent()

# --- Instâncias dos Agentes de Temperatura ---
temperature_behavioral_agent = EmailBehavioralAgent()

# --- Instância do Agente Diretor ---
director_agent = EmailDirectorAgent()

# --- Instância do Agente Sumarizador ---
formal_summarizer_agent = FormalSummarizerAgent()

# --- Instância do Juri ---
legal_context_synthesizer_agent = LegalContextSynthesizerAgent()
conservative_advocate_agent = ConservativeAdvocateAgent()
strategic_advocate_agent = StrategicAdvocateAgent()
judicial_arbiter_agent = JudicialArbiterAgent()

__all__ = [
    "context_miner_agent",
    "context_synthesizer_agent",
    "extraction_subject_agent",
    "extraction_legal_financial_agent",
    "extraction_stage_agent",
    "extraction_manager_agent",
    "temperature_behavioral_agent",
    "director_agent",
    "formal_summarizer_agent",
    "validator_agent ",
    "refiner_agent ",
    "legal_context_synthesizer_agent",
    "conservative_advocate_agent",
    "strategic_advocate_agent",
    "judicial_arbiter_agent",
]
