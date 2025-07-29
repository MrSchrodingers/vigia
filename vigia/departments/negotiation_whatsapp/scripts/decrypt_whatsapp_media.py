from base64 import b64decode
from Crypto.Cipher import AES
from Crypto.Hash   import HMAC, SHA256
from Crypto.Protocol.KDF import HKDF

# Só 'audio' é relevante no fluxo de ingestão
_MEDIA_INFO = {
    "audio": b"WhatsApp Audio Keys",
}

# ──────────────────────────────────────────────────────────────
def decrypt_whatsapp_media(enc: bytes, media_key_b64: str) -> bytes:
    """
    Descriptografa nota de voz .enc.
    Detecta se o IV vem do HKDF (A) ou do arquivo (B).
    """
    if len(enc) <= 10:
        raise ValueError("Arquivo muito pequeno para conter MAC.")

    media_key = b64decode(media_key_b64)
    iv_hkdf, cipher_key, mac_key = _derive_keys(media_key)

    # Variante A – IV só do HKDF
    if _valid_mac(iv_hkdf, enc[:-10], enc[-10:], mac_key):
        return _decrypt(enc[:-10], cipher_key, iv_hkdf)

    # Variante B – IV embutido nos 16 bytes iniciais
    iv_file      = enc[:16]
    ciphertext   = enc[16:-10]
    mac_original = enc[-10:]
    if _valid_mac(iv_file, ciphertext, mac_original, mac_key):
        return _decrypt(ciphertext, cipher_key, iv_file)

    raise ValueError("HMAC mismatch – chave ou arquivo incorretos")

# ──────────────────────────────────────────────────────────────
def _derive_keys(media_key: bytes):
    km = HKDF(media_key, 80, b"", SHA256, context=_MEDIA_INFO["audio"])
    return km[:16], km[16:48], km[48:80]

def _valid_mac(iv: bytes, ct: bytes, mac: bytes, mac_key: bytes) -> bool:
    return HMAC.new(mac_key, iv + ct, SHA256).digest()[:10] == mac

def _decrypt(ct: bytes, key: bytes, iv: bytes) -> bytes:
    plain = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    return plain[:-plain[-1]]           # remove PKCS‑7
