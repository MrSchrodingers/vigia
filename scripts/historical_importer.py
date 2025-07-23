# scripts/historical_importer.py
import logging
import requests
from collections import defaultdict

from db.session import SessionLocal
from vigia.config import settings
from vigia.services.database_service import save_raw_conversation

RECORDS_PER_PAGE = 50
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def main():
    logging.info("Iniciando INGESTÃO de histórico da Evolution API para o banco de dados.")
    
    current_page = 1
    total_pages = 1
    db = SessionLocal()

    try:
        while current_page <= total_pages:
            logging.info(f"Buscando página {current_page}/{total_pages}...")
            response = requests.post(
                f"{settings.EVOLUTION_BASE_URL}/chat/findMessages/{settings.INSTANCE_NAME}",
                headers={"apikey": settings.API_KEY},
                json={"page": current_page, "size": RECORDS_PER_PAGE, "sort": "desc"} # 'desc' para pegar os mais recentes primeiro
            )
            response.raise_for_status()
            data = response.json()
            
            records = data.get("messages", {}).get("records", [])
            if not records:
                logging.info("Nenhuma mensagem nesta página. Concluindo.")
                break

            # Processa e agrupa as mensagens da página atual
            conversations_in_page = defaultdict(list)
            for msg in records:
                conversation_id = msg.get("key", {}).get("remoteJid")
                external_id = msg.get("key", {}).get("id")
                if not conversation_id or not external_id: 
                    continue
                
                sender = "Negociador" if msg.get("key", {}).get("fromMe") else "Cliente"
                timestamp = msg.get("messageTimestamp", 0)
                message_type = msg.get("messageType")
                text_content = ""

                if message_type == "conversation":
                    text_content = msg.get("message", {}).get("conversation", "")
                elif message_type == "audioMessage":
                    text_content = "[MENSAGEM DE ÁUDIO]"
                elif message_type == "documentMessage":
                    filename = msg.get("message", {}).get("documentMessage", {}).get("fileName", "documento")
                    text_content = f"[DOCUMENTO ENVIADO: {filename}]"
                elif message_type == "imageMessage":
                    text_content = "[IMAGEM ENVIADA]"
                else:
                    text_content = f"[{message_type}]"
                
                if text_content and text_content.startswith("*") and ":*" in text_content:
                    text_content = text_content.split(":*", 1)[-1].strip()

                conversations_in_page[conversation_id].append({
                    "sender": sender, "text": text_content, "timestamp": timestamp, "external_id": external_id
                })

            # Salva todas as conversas processadas da página no banco de dados
            for conv_id, messages in conversations_in_page.items():
                save_raw_conversation(db=db, conversation_jid=conv_id, messages=messages)

            logging.info(f"Página {current_page} processada e salva no banco.")
            total_pages = data.get("messages", {}).get("pages", 1)
            current_page += 1

    except Exception as e:
        logging.error(f"Erro durante a ingestão: {e}", exc_info=True)
    finally:
        db.close()
            
    logging.info("Ingestão de dados brutos finalizada.")

if __name__ == "__main__":
    main()