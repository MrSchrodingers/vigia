from fastapi import FastAPI, Request, BackgroundTasks
from .worker import process_conversation_task

app = FastAPI(
    title="Vigia API",
    description="API de ingestão de webhooks para o Agente Supervisor.",
    version="0.1.0"
)

@app.get("/", tags=["Health Check"])
async def read_root():
    return {"status": "Vigia API está no ar!"}

@app.post("/webhook/evolution", tags=["Webhooks"])
async def receive_evolution_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Recebe um webhook da Evolution API, valida e enfileira para processamento.
    """
    payload = await request.json()
    
    # Enfileira a tarefa para ser processada em background pelo worker
    background_tasks.add_task(process_conversation_task.delay, payload)
    
    return {"status": "success", "message": "Payload recebido e enfileirado."}
