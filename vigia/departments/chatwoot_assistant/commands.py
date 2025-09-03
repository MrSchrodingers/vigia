# vigia/departments/chatwoot_assistant/commands.py
import asyncio
import json
from datetime import datetime
import logging

# Reutilizamos a lógica de orquestração e os agentes já existentes
from vigia.departments.negotiation_whatsapp.core.orchestrator import (
    run_extraction_department,
    run_temperature_department,
    _preprocess_audio_segments # Essencial para o resumo
)
from vigia.departments.negotiation_whatsapp.agents.director_agent import director_agent

async def get_summary(conversation_history: str, context_from_pipedrive: str, last_message_date: datetime):
    """
    Gera um resumo da negociação, processando áudios e executando os agentes de extração e temperatura.
    """
    try:
        logging.info("Iniciando geração de resumo...")
        ref_date = last_message_date.strftime('%Y-%m-%d')
        
        # 1. Pré-processa áudios, transcrevendo-os com Whisper
        history_with_transcriptions = await _preprocess_audio_segments(conversation_history, ref_date)
        
        # 2. Combina contexto do Pipedrive com o histórico para dar mais informação aos agentes
        history_with_context = f"DADOS DO PIPEDRIVE:\n{context_from_pipedrive}\n\n---\n\nHISTÓRICO DA CONVERSA:\n{history_with_transcriptions}"
        
        # 3. Roda os agentes de extração e temperatura em paralelo para economizar tempo
        extraction_str, temperature_str = await asyncio.gather(
            run_extraction_department(history_with_context, ref_date),
            run_temperature_department(history_with_transcriptions)
        )
        
        # 4. Formata a saída de forma clara e legível para o operador
        extraction_data = json.loads(extraction_str)
        temperature_data = json.loads(temperature_str)

        summary = f"""
**Resumo da Negociação:**
- **Status Atual:** {extraction_data.get('status', 'Não identificado')}
- **Sentimento Geral:** {temperature_data.get('temperatura_final', 'Não identificado')} (Tendência: {temperature_data.get('tendencia', 'N/A')})
- **Resumo da Conversa:** {extraction_data.get('resumo_negociacao', 'Não foi possível resumir.')}

**Pontos Chave do Cliente:**
- {(' | '.join(extraction_data.get('pontos_chave_cliente', ['Nenhum'])))}

**Próximos Passos Sugeridos:**
- {(' | '.join(extraction_data.get('proximos_passos', ['Nenhum'])))}
"""
        logging.info("Resumo gerado com sucesso.")
        return summary.strip()
        
    except Exception as e:
        logging.error(f"Falha ao gerar resumo: {e}", exc_info=True)
        return "Ocorreu um erro ao processar o resumo. A equipe técnica foi notificada."

async def get_pipedrive_info(context_from_pipedrive: str):
    """
    Apenas exibe os dados brutos do Pipedrive que já foram buscados.
    """
    return f"**Dados do Pipedrive:**\n\n{context_from_pipedrive}"

async def get_recommended_action(conversation_history: str, context_from_pipedrive: str, conversation_jid: str):
    """
    Executa o pipeline completo para obter a recomendação do agente Diretor.
    """
    try:
        logging.info(f"Gerando ação recomendada para {conversation_jid}...")
        ref_date = datetime.now().strftime('%Y-%m-%d')
        
        history_with_transcriptions = await _preprocess_audio_segments(conversation_history, ref_date)
        history_with_context = f"DADOS DO PIPEDRIVE:\n{context_from_pipedrive}\n\n---\n\nHISTÓRICO DA CONVERSA:\n{history_with_transcriptions}"
        
        extraction_str, temperature_str = await asyncio.gather(
            run_extraction_department(history_with_context, ref_date),
            run_temperature_department(history_with_transcriptions)
        )
        
        director_output = await director_agent.execute(extraction_str, temperature_str, conversation_jid)
        
        # Verifica se a saída é uma chamada de função (para o Pipedrive, por exemplo)
        if isinstance(director_output, dict) and director_output.get('type') == 'function_call':
            action = director_output['name']
            args = director_output['args']
            return f"**Ação Recomendada (Function Call):**\n- **Ferramenta:** `{action}`\n- **Parâmetros:** `{args}`"
        else:
            return f"**Ação Recomendada:**\n- {director_output}"
            
    except Exception as e:
        logging.error(f"Falha ao gerar ação recomendada: {e}", exc_info=True)
        return "Ocorreu um erro ao gerar a ação recomendada."