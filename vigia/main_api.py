import logging
import os
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from vigia.api.routers import auth, chat, negotiations, processes, system
from vigia.api.routers.actions import negotiation_actions, process_actions
from vigia.utils.main_utils import normalize_chatwoot_payload
from .worker import process_conversation_task
from .config import settings

logging.basicConfig(level=settings.LOG_LEVEL)

app = FastAPI(
    title="Vigia API",
    description="API para o sistema de negociação e análise jurídica.",
    version="1.0.0"
)

WEBHOOK_SECRET = os.getenv("CHATWOOT_WEBHOOK_SECRET", "") 

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Health Check"])
async def read_root():
    return {"status": "Vigia API está no ar!"}

app.include_router(auth.router)
app.include_router(system.router)
app.include_router(negotiations.router)
app.include_router(processes.router)
app.include_router(processes.actions_router)  
app.include_router(processes.transit_router)
app.include_router(chat.router)
app.include_router(negotiation_actions.router)
app.include_router(process_actions.router) 

@app.post("/webhook/evolution", tags=["Webhooks"])
async def receive_evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe um webhook da Evolution API (WhatsApp).
    Adiciona a fonte 'whatsapp' e enfileira para processamento.
    """
    payload = await request.json()
    
    # Adiciona a informação da fonte para o roteamento do Diretor-Geral
    payload["source"] = "whatsapp"
    
    background_tasks.add_task(process_conversation_task.delay, payload)
    
    return {"status": "success", "message": "Payload do WhatsApp recebido e enfileirado."}

@app.post("/webhook/microsoft-graph", tags=["Webhooks"])
async def receive_email_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe um webhook da Microsoft Graph API (E-mail).
    Adiciona a fonte 'email' e enfileira para processamento.
    """
    payload = await request.json()
    
    payload["source"] = "email"
    
    background_tasks.add_task(process_conversation_task.delay, payload)
    
    return {"status": "success", "message": "Payload do E-mail recebido e enfileirado."}

@app.post("/webhook/chatwoot", tags=["Webhooks"])
async def receive_chatwoot_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
        logging.info("Chatwoot payload: %s", payload)

        # # (opcional) token simples via query string
        # token_qs = request.query_params.get("token")
        # if WEBHOOK_SECRET and token_qs != WEBHOOK_SECRET:
        #     raise HTTPException(status_code=401, detail="unauthorized")

        norm = normalize_chatwoot_payload(payload)

        # ignore eventos irrelevantes
        if norm["event"] not in {"macro.executed", "message_created"}:
            return {"status": "ignored", "reason": "event_not_supported"}

        # se for message_created, exija que venha de agente e que tenha slash
        if norm["event"] == "message_created" and not (norm["is_agent_message"] and norm["command"]):
            return {"status": "ignored", "reason": "not_a_command_or_not_agent"}

        # anexe source + norm ao payload encaminhado
        payload["source"] = "chatwoot"
        payload["_norm"] = norm

        background_tasks.add_task(process_conversation_task.delay, payload)
        return {"status": "queued", "command": norm["command"] or "(macro)"}

    except Exception as e:
        logging.exception("Erro no webhook Chatwoot")
        return {"status": "error", "message": str(e)}