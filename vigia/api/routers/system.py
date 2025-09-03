from fastapi import APIRouter, Depends, BackgroundTasks
from vigia.api import dependencies, schemas
from vigia.departments.negotiation_email.scripts.historical_importer import main as run_email_sync
from vigia.services.jusbr_service import jusbr_service

router = APIRouter(
    prefix="/api/system",
    tags=["System"],
    dependencies=[Depends(dependencies.get_current_user)],
)

@router.get("/jusbr-status", response_model=schemas.JusbrStatus)
async def get_jusbr_status():
    """
    Verifica o status atual do login no Jus.br.
    Mapeia para a função checkJusBrLogin() no frontend.
    """
    is_active = await jusbr_service.check_login_status()
    return {"is_active": is_active}

@router.post("/jusbr-login", response_model=schemas.JusbrStatus)
async def force_jusbr_login(background_tasks: BackgroundTasks):
    """
    Dispara a rotina de login do Jus.br em background.
    Mapeia para a função handleRefreshLogin().
    """
    background_tasks.add_task(jusbr_service.refresh_login())
    return {"is_active": False, "message": "Login refresh initiated."}

@router.post("/sync-emails", response_model=schemas.ActionResponse)
async def trigger_email_sync(background_tasks: BackgroundTasks):
    """
    Dispara a sincronização de e-mails em background.
    Mapeia para a função handleEmailSync().
    """
    background_tasks.add_task(run_email_sync)
    return {"status": "success", "message": "Email synchronization started in background."}