import logging
import httpx
import google.generativeai as genai
import asyncio  
import time     
from collections import deque 

from vigia.departments.negotiation_whatsapp.core import tools
from ..config import settings

# --- Configuração do Rate Limiter para o Gemini ---
GEMINI_RPM_LIMIT = 1000  # Requisições por minuto
GEMINI_WINDOW_SECONDS = 60
gemini_request_timestamps = deque()

if settings.LLM_PROVIDER == "gemini" and settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

def _clean_llm_response(response_text: str) -> str:
    if not isinstance(response_text, str): 
        return ""
    if response_text.strip().startswith("```json"):
        response_text = response_text.strip()[7:-3]
    elif response_text.strip().startswith("```"):
        response_text = response_text.strip()[3:-3]
    try:
        start = response_text.find('{')
        end = response_text.rfind('}')
        if start != -1 and end != -1:
            return response_text[start:end+1]
    except Exception:
        pass
    return response_text.strip()

async def llm_call(
    system_prompt: str,
    user_prompt: str,
    use_tools: bool = False
) -> str | dict:
    """
    Função AGNÓSTICA e ASSÍNCRONA que chama o provedor de LLM.
    Pode opcionalmente usar function calling.
    """
    logging.info(f"Chamando LLM provider (async): {settings.LLM_PROVIDER}")
    raw_response = ""

    available_tools = {
        "criar_atividade_no_pipedrive": tools.CriarAtividadeNoPipedrive,
        "alertar_supervisor": tools.AlertarSupervisor,
    }

    if settings.LLM_PROVIDER == "gemini":
        raw_response = await _call_gemini_async(
            system_prompt, user_prompt, use_tools, available_tools
        )
    elif settings.LLM_PROVIDER == "ollama":
        raw_response = await _call_ollama_async(system_prompt, user_prompt)
    else:
        return '{"error": "LLM provider not configured"}'

    if isinstance(raw_response, dict):
        logging.info(f"LLM solicitou chamada de função: {raw_response}")
        return raw_response

    cleaned_response = _clean_llm_response(raw_response)
    logging.debug(f"Resposta bruta: {raw_response}")
    logging.info(f"Resposta limpa: {cleaned_response}")
    return cleaned_response


async def _call_gemini_async(
    system_prompt: str,
    user_prompt: str,
    use_tools: bool,
    available_tools: dict
) -> str | dict:
    """Versão assíncrona para chamar o Gemini, com suporte a ferramentas e rate limiting."""
    now = time.monotonic()
    
    # Remove timestamps que já saíram da janela de 60 segundos
    while gemini_request_timestamps and now - gemini_request_timestamps[0] > GEMINI_WINDOW_SECONDS:
        gemini_request_timestamps.popleft()
        
    # Se o número de requisições na janela atual atingiu o limite, espera
    if len(gemini_request_timestamps) >= GEMINI_RPM_LIMIT:
        oldest_request_time = gemini_request_timestamps[0]
        wait_time = (oldest_request_time + GEMINI_WINDOW_SECONDS) - now
        logging.warning(f"Limite de requisições do Gemini atingido. Aguardando por {wait_time:.2f} segundos.")
        await asyncio.sleep(wait_time)
    
    # Adiciona o timestamp da requisição atual
    gemini_request_timestamps.append(time.monotonic())

    try:
        model_name = "gemini-2.5-flash"
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt,
            tools=list(available_tools.values()) if use_tools else None
        )
        
        response = await model.generate_content_async(
            user_prompt,
            tool_config={"function_calling_config": "ANY"} if use_tools else None
        )

        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if part.function_call:
                function_call = part.function_call
                return {
                    "type": "function_call",
                    "name": function_call.name,
                    "args": {key: value for key, value in function_call.args.items()}
                }
        
        return response.text
    except Exception as e:
        logging.error(f"Erro na API do Gemini (async): {e}")
        return '{"error": "Gemini API call failed"}'

async def _call_ollama_async(system_prompt: str, user_prompt: str) -> str:
    """Versão assíncrona para chamar o Ollama."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "model": settings.OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "stream": False, "format": "json"
            }
            response = await client.post(f"{settings.OLLAMA_API_URL}/api/chat", json=payload)
            response.raise_for_status()
            return response.json()['message']['content']
    except httpx.RequestError as e:
        logging.error(f"Erro ao chamar a API do Ollama (async): {e}")
        return '{"error": "Ollama API call failed"}'