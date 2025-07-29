# Ficheiro: debug_downloader.py

import base64
import requests
import logging
from Crypto.Cipher import AES
from Crypto.Hash import HMAC, SHA256
from Crypto.Protocol.KDF import HKDF

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- PREENCHA OS DADOS DE UMA MENSAGEM QUE FALHOU AQUI ---
# Usei os dados do primeiro áudio do seu log original como exemplo.
# Você pode trocar por um vídeo ou documento se quiser.
MESSAGE_DATA = {
    "url": "https://mmg.whatsapp.net/v/t62.7161-24/19434322_4090714151215962_2401308740173078123_n.enc?ccb=11-4&oh=01_Q5Aa2AGxAYejgrffCUxnsG6FiEkv0xAJTLC-Uvlscrt7r_ndVg&oe=68B064C5&_nc_sid=5e03e0&mms3=true",
    "media_key_b64": "E2k8shWN9DXcNX1/Mq+znwYUktOprAhKrctHoSQApaw=",
    "info_string": "WhatsApp Video Keys",  # Mude para "WhatsApp Video Keys", etc., se estiver a testar outro tipo
    "expected_size_str": "13464983"  # Este é o campo "fileLength" do JSON da mensagem original
}
# ---------------------------------------------------------

def decrypt_whatsapp_media(encrypted_data, media_key_b64, info_string):
    """
    Decifra um arquivo de mídia do WhatsApp (áudio, vídeo, etc.)
    usando a "info string" apropriada para o tipo de mídia.
    """
    try:
        media_key = base64.b64decode(media_key_b64)
        iv = encrypted_data[:16]
        ciphertext = encrypted_data[16:-10]
        mac_original = encrypted_data[-10:]
        info_bytes = info_string.encode('utf-8')
        key_material = HKDF(media_key, 80, b'', SHA256, 1, context=info_bytes)
        aes_key = key_material[:32]
        mac_key = key_material[32:64]
        mac_validation = HMAC.new(mac_key, iv + ciphertext, SHA256).digest()[:10]
        if mac_original != mac_validation:
            raise ValueError("A validação HMAC falhou. O arquivo pode estar corrompido ou a chave está incorreta.")
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        decrypted_data_with_padding = cipher.decrypt(ciphertext)
        padding_length = decrypted_data_with_padding[-1]
        return decrypted_data_with_padding[:-padding_length]
    except Exception as e:
        logging.error(f"Erro ao decifrar mídia: {e}")
        return None

def main():
    logging.info("--- Iniciando Depurador de Download e Decriptografia ---")
    
    url = MESSAGE_DATA["url"]
    media_key_b64 = MESSAGE_DATA["media_key_b64"]
    info_string = MESSAGE_DATA["info_string"]
    expected_size = int(MESSAGE_DATA["expected_size_str"])

    try:
        logging.info(f"Baixando mídia de: {url}")
        media_response = requests.get(url)
        media_response.raise_for_status() # Lança um erro se o status não for 200 (OK)

        # --- Logs de Depuração ---
        logging.info(f"Cabeçalhos da resposta do download: {media_response.headers}")
        actual_size = len(media_response.content)
        
        logging.info(f"Tamanho esperado (do JSON da API): {expected_size} bytes")
        logging.info(f"Tamanho real do download:          {actual_size} bytes")

        if actual_size != expected_size:
            logging.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            logging.error("!!! ALERTA: O tamanho do ficheiro baixado NÃO CORRESPONDE ao esperado!")
            logging.error("!!! Isto é a causa provável do erro de HMAC.")
            logging.error("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        else:
            logging.info("O tamanho do ficheiro corresponde ao esperado. A chave pode estar incorreta.")
        
        # Tenta decifrar mesmo que o tamanho seja diferente, para confirmar o erro
        decrypted_media = decrypt_whatsapp_media(media_response.content, media_key_b64, info_string)

        if decrypted_media:
            logging.info("SUCESSO! A mídia foi decifrada.")
        else:
            logging.error("FALHA: A decriptografia falhou como esperado.")

    except requests.exceptions.RequestException as e:
        logging.error(f"Erro de rede ao tentar baixar a mídia: {e}")
    except Exception as e:
        logging.error(f"Ocorreu um erro inesperado: {e}")

if __name__ == "__main__":
    main()