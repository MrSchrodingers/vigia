from fastapi import FastAPI, Request, BackgroundTasks
from .worker import process_conversation_task

app = FastAPI(
    title="Vigia API",
    description="API de ingestão de webhooks para o Agente Supervisor.",
    version="0.2.0"
)

@app.get("/", tags=["Health Check"])
async def read_root():
    return {"status": "Vigia API está no ar!"}

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