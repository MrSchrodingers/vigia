import logging
from vigia.departments.negotiation_email.adapters.graph_api_adapter import GraphApiAdapter
from vigia.departments.negotiation_email.adapters.email_repository import PostgresEmailRepository
from vigia.departments.negotiation_email.services.email_importer_service import EmailImporterService

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    """
    Ponto de entrada para executar o processo de importação de e-mails.
    """
    logging.info("Iniciando INGESTÃO de histórico da Microsoft Graph API para o banco de dados do VigIA.")

    # 1. Instanciar as dependências (Adaptadores)
    graph_client = GraphApiAdapter()
    email_repository = PostgresEmailRepository()

    # 2. Instanciar o serviço de domínio com as dependências
    importer_service = EmailImporterService(
        graph_client=graph_client,
        email_repo=email_repository
    )

    # 3. Executar a importação
    try:
        importer_service.run_import_for_all_accounts()
        logging.info("Processo de ingestão de histórico de e-mail finalizado com sucesso. ✅")
    except Exception as e:
        logging.error(f"Ocorreu um erro crítico durante a ingestão de e-mails: {e}", exc_info=True)

if __name__ == "__main__":
    main()