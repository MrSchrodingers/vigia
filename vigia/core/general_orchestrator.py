import logging
import importlib

# Mapeia a 'source' do payload para o módulo do orquestrador departamental
DEPARTMENT_MAPPING = {
    "whatsapp": "vigia.departments.negotiation_whatsapp.core.orchestrator",
    "email": "vigia.departments.negotiation_email.core.orchestrator",
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
        # Importa dinamicamente o módulo do orquestrador do departamento
        department_orchestrator_module = importlib.import_module(module_path)
        
        # Por convenção, cada orquestrador departamental terá uma função principal
        # chamada run_department_pipeline
        logging.info(f"Direcionando tarefa para o departamento: {source}")
        await department_orchestrator_module.run_department_pipeline(payload)

    except ImportError:
        logging.error(f"Falha ao importar o módulo do departamento: {module_path}")
    except AttributeError:
        logging.error(f"A função 'run_department_pipeline' não foi encontrada no módulo {module_path}")
    except Exception as e:
        logging.error(f"Erro inesperado ao executar o pipeline do departamento {source}: {e}", exc_info=True)