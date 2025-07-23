import logging
import httpx
import google.generativeai as genai
from ..config import settings

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

async def llm_call(system_prompt: str, user_prompt: str) -> str:
    """
    Função AGNÓSTICA e ASSÍNCRONA que chama o provedor de LLM.
    """
    logging.info(f"Chamando LLM provider (async): {settings.LLM_PROVIDER}")
    raw_response = ""
    if settings.LLM_PROVIDER == "gemini":
        raw_response = await _call_gemini_async(system_prompt, user_prompt)
    elif settings.LLM_PROVIDER == "ollama":
        raw_response = await _call_ollama_async(system_prompt, user_prompt)
    else:
        return '{"error": "LLM provider not configured"}'

    cleaned_response = _clean_llm_response(raw_response)
    logging.debug(f"Resposta bruta: {raw_response}")
    logging.info(f"Resposta limpa: {cleaned_response}")
    return cleaned_response

async def _call_gemini_async(system_prompt: str, user_prompt: str) -> str:
    """Versão assíncrona para chamar o Gemini."""
    try:
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash-latest",
            system_instruction=system_prompt
        )
        # A biblioteca do Gemini já suporta chamadas assíncronas
        response = await model.generate_content_async(user_prompt)
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