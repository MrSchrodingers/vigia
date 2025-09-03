
import logging
import importlib

DEPARTMENT_MAPPING = {
    "whatsapp": "vigia.departments.negotiation_whatsapp.core.orchestrator",
    "email": "vigia.departments.negotiation_email.core.orchestrator",
    "chatwoot": "vigia.departments.chatwoot_assistant.orchestrator"
}

async def route_to_department(payload: dict):
    """
    O Diretor-Geral.
    Lê a fonte do payload e direciona para o orquestrador departamental correto.
    """
    source = payload.get("source")
    if not source:
        logging.error("A 'source' não foi especificada no payload. Não é possível rotear.")
        return

    module_path = DEPARTMENT_MAPPING.get(source)
    if not module_path:
        logging.error(f"Nenhum departamento encontrado para a source: '{source}'")
        return

    try:
        department_module = importlib.import_module(module_path)
        
        if hasattr(department_module, 'handle_task'):
            await department_module.handle_task(payload)
        else:
            await department_module.run_department_pipeline(payload)

    except ImportError:
        logging.error(f"Falha ao importar o módulo do departamento: {module_path}")
    except AttributeError as e:
        logging.error(f"Função de entrada não encontrada no módulo {module_path}: {e}")
    except Exception as e:
        logging.error(f"Erro inesperado ao executar o pipeline do departamento {source}: {e}", exc_info=True)