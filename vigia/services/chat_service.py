
import re
from sqlalchemy.orm import Session
from . import  llm_service
from db import models

async def generate_assistant_response(db: Session, user_message: str, session_id: str) -> str:
    """
    Gera uma resposta do assistente de IA, enriquecendo o prompt com contexto.
    """
    # 1. Extrair entidades (ex: número do processo) da mensagem do usuário
    process_number_match = re.search(r'\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}', user_message)
    context = ""

    # 2. Buscar contexto no banco de dados
    if process_number_match:
        process_number = process_number_match.group(0)
        process = db.query(models.LegalProcess).filter(models.LegalProcess.process_number == process_number).first()
        if process:
            context += f"\n\n--- Contexto do Processo {process.process_number} ---\n"
            context += f"Título: {process.title}\n"
            context += f"Status: {process.status}\n"
            context += f"Valor: {process.value}\n"
            if process.summary_content:
                context += f"Resumo IA: {process.summary_content}\n"
            context += "---------------------------------------------------\n"
        else:
            context += f"\n(Não encontrei dados para o processo {process_number} no banco de dados.)\n"

    # 3. Construir o prompt
    system_prompt = (
        "Você é um assistente jurídico inteligente. "
        "Responda às perguntas do usuário de forma concisa e direta. "
        "Utilize o contexto fornecido para embasar suas respostas."
    )
    
    # Obter histórico da conversa para dar contexto ao LLM
    session_history = db.query(models.ChatMessage)\
        .filter(models.ChatMessage.session_id == session_id)\
        .order_by(models.ChatMessage.timestamp.asc()).all()

    full_user_prompt = "Histórico da Conversa:\n"
    for msg in session_history:
        full_user_prompt += f"{msg.role}: {msg.content}\n"
    
    full_user_prompt += f"\nContexto Adicional:\n{context}\n\nNova Pergunta do Usuário: {user_message}"

    # 4. Chamar o serviço de LLM
    response = await llm_service.llm_call(
        system_prompt=system_prompt,
        user_prompt=full_user_prompt,
    )
    
    return response