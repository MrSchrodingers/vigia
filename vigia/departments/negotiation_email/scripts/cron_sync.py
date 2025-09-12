import asyncio
from db import models
from db.session import SessionLocal
from vigia.departments.negotiation_email.services.discord_notifier import create_update_embed, send_discord_notification
from vigia.services import crud, jusbr_service

async def sync_all_processes():
    print("Iniciando a sincronização de processos...")
    db = SessionLocal()
    try:
        # 1. Pega todos os grupos de processos distintos para sincronizar
        process_groups = db.query(models.LegalProcess.grouping_id).distinct().all()
        process_numbers_to_sync = [item[0] for item in process_groups if item[0]]

        print(f"Encontrados {len(process_numbers_to_sync)} grupos de processos para verificar.")

        for number in process_numbers_to_sync:
            print(f"Sincronizando processo: {number}...")
            
            # 2. Busca os dados atuais do processo no banco
            current_processes = db.query(models.LegalProcess).filter_by(grouping_id=number).all()
            
            # Mapeia as movimentações existentes para fácil comparação
            existing_movements = {}
            for proc in current_processes:
                key = (proc.instance, proc.degree_numero)
                existing_movements[key] = {mov.description for mov in proc.movements}

            # 3. Busca os dados mais recentes da API
            try:
                # O serviço deve ser adaptado para retornar a estrutura completa da busca
                latest_data = await jusbr_service.get_processo_search_results(number)
                if not latest_data or "erro" in latest_data:
                    print(f"Erro ao buscar dados para {number}: {latest_data.get('erro')}")
                    continue
            except Exception as e:
                print(f"Exceção ao buscar dados para {number}: {e}")
                continue

            # 4. Compara e notifica
            tramitacoes = latest_data.get("content", [{}])[0].get("tramitacoes", [])
            for tramitacao_data in tramitacoes:
                key = crud.get_tramitacao_identifier(tramitacao_data)
                current_movs_set = existing_movements.get(key, set())
                
                new_movements_list = []
                for mov in tramitacao_data.get("movimentos", []):
                    if mov['description'] not in current_movs_set:
                        new_movements_list.append({
                            "date": mov['dataHora'],
                            "description": mov['description']
                        })

                if new_movements_list:
                    print(f"Novas movimentações encontradas para {number} (Instância: {key[0]}): {len(new_movements_list)}")
                    
                    # Envia notificação para o Discord
                    process_title = tramitacao_data.get("classe", [{}])[0].get("descricao", "Processo")
                    embed = create_update_embed(number, new_movements_list, process_title)
                    send_discord_notification(
                        message=f" novas movimentações detectadas!",
                        embed=embed
                    )
                    
                    # Atualiza o processo no banco
                    # O CRUD já deve estar preparado para isso
                    crud.upsert_process_from_jusbr_data(db, latest_data, user_id="system") # Ou o ID de um usuário admin
                else:
                    print(f"Nenhuma nova movimentação para {number} (Instância: {key[0]}).")
                    
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(sync_all_processes())