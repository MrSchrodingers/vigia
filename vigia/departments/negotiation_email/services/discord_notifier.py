from datetime import datetime, timezone
import httpx
import os

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

def send_discord_notification(message: str, embed: dict = None):
    """
    Envia uma notificação para um canal do Discord via webhook.
    """
    if not DISCORD_WEBHOOK_URL:
        print("AVISO: DISCORD_WEBHOOK_URL não configurada. Notificação não enviada.")
        return

    payload = {
        "content": message,
    }
    if embed:
        payload["embeds"] = [embed]

    try:
        with httpx.Client() as client:
            response = client.post(DISCORD_WEBHOOK_URL, json=payload)
            response.raise_for_status()
        print("Notificação enviada ao Discord com sucesso.")
    except httpx.HTTPStatusError as e:
        print(f"Erro ao enviar notificação ao Discord: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        print(f"Erro inesperado ao notificar o Discord: {e}")

# Exemplo de como criar um "embed" (bloco formatado)
def create_update_embed(process_number: str, new_movements: list, title: str):
    description = ""
    for mov in new_movements:
        # Formata a data para um formato mais legível
        date_str = mov.get('date', 'Data não informada')
        if isinstance(date_str, str):
            try:
                date_obj = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                date_str = date_obj.strftime('%d/%m/%Y %H:%M')
            except ValueError:
                pass # Mantém a string original se não for um formato ISO válido
        
        description += f"**{date_str}**: {mov.get('description', 'N/A')}\n"

    embed = {
        "title": f"🔔 Atualização no Processo: {title}",
        "description": f"**Número:** `{process_number}`\n\n**Novas Movimentações:**\n{description}",
        "color": 16762880, # Cor laranja/amarelo
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    return embed