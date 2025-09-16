import argparse
import asyncio
import logging
from typing import Optional

from sqlalchemy.orm import Session

from db.session import SessionLocal
from vigia.departments.negotiation_email.services import cpj_service
from vigia.services import crud
from vigia.services.jusbr_service import jusbr_service

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


async def main() -> Optional[int]:
    parser = argparse.ArgumentParser(
        description="Sincroniza dados do CPJ e enriquece com informações do Jus.br."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Número de processos a serem sincronizados (padrão: 10).",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        help="O UUID do usuário 'dono' padrão para novos processos.",
    )
    args = parser.parse_args()

    logging.info(
        "Iniciando descoberta de %d processos no CPJ para sincronização completa.",
        args.limit,
    )
    db: Session = SessionLocal()

    try:
        processos_do_cpj = cpj_service.get_latest_updated_cpj_processes(
            limit=args.limit
        )

        if not processos_do_cpj:
            logging.info("Nenhum processo novo ou atualizado encontrado no CPJ.")
            return 0

        enriquecidos_count = 0
        for cpj_data in processos_do_cpj:
            legal_process = cpj_service.sync_process_from_cpj(
                db=db, user_id=args.user_id, cpj_data=cpj_data
            )

            if not legal_process or not legal_process.process_number:
                logging.warning(
                    "Processo do CPJ não pôde ser sincronizado ou não possui um número válido. Pulando enriquecimento."
                )
                continue

            try:
                logging.info(
                    f"Processo {legal_process.process_number} sincronizado do CPJ. Buscando detalhes completos no Jus.br..."
                )
                jusbr_data_list = await jusbr_service.get_processo_details_with_docs(
                    legal_process.process_number
                )

                if not jusbr_data_list or jusbr_data_list[0].get("erro"):
                    logging.warning(
                        f"Não foram encontrados dados no Jus.br para o processo {legal_process.process_number}. Detalhe: {jusbr_data_list[0].get('erro', 'Resposta vazia')}"
                    )
                    continue

                for process_data in jusbr_data_list:
                    crud.upsert_process_from_jusbr_data(
                        db, process_data, user_id=args.user_id
                    )

                logging.info(
                    f"Processo {legal_process.process_number} enriquecido com sucesso via Jus.br."
                )
                enriquecidos_count += 1
            except Exception as e:
                logging.error(
                    f"Falha ao enriquecer o processo {legal_process.process_number} via Jus.br: {e}",
                    exc_info=True,
                )

        logging.info(
            "Processo de descoberta concluído. %d processos enriquecidos.",
            enriquecidos_count,
        )
        return enriquecidos_count

    except Exception as e:
        logging.error("Erro fatal durante a descoberta no CPJ: %s", e, exc_info=True)
        return None
    finally:
        try:
            db.close()
        except Exception:
            logging.exception("Erro ao fechar sessão DB em sync_cpj.main().")


if __name__ == "__main__":
    asyncio.run(main())
