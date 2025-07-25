
import argparse
import logging
import asyncio
import json

from vigia.departments.negotiation_email.core.orchestrator import run_department_pipeline

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main_async():
    """
    Script para reanalisar uma única thread de e-mail a partir de seu conversation_id.
    """
    parser = argparse.ArgumentParser(description="Reanalisa uma thread de e-mail do banco de dados.")
    parser.add_argument("--thread", required=True, help="O ID da conversa (conversation_id) da thread de e-mail.")
    parser.add_argument("--salvar", action="store_true", help="Salva o resultado da análise no banco de dados.")
    args = parser.parse_args()

    logging.info(f"Iniciando reanálise para a thread: {args.thread}")

    # O payload é simples, pois o orquestrador buscará todos os dados do banco
    payload = {
        "conversation_id": args.thread,
        "save_result": args.salvar  # Passa a flag para o orquestrador
    }

    try:
        # Chama diretamente o pipeline do departamento de e-mail
        final_report = await run_department_pipeline(payload)

        if final_report:
            logging.info("Reanálise concluída com sucesso.")
            print("\n--- RELATÓRIO DE REANÁLISE COMPLETO ---")
            print(json.dumps(final_report, indent=2, ensure_ascii=False))
            print("-----------------------------------------\n")
        else:
            logging.warning("A reanálise não produziu um relatório. Verifique os logs para mais detalhes.")

    except Exception as e:
        logging.error(f"Ocorreu um erro durante a reanálise da thread {args.thread}: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main_async())