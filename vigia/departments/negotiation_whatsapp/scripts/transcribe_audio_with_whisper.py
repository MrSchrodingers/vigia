import whisper
import torch
import tempfile
import os
import logging
from vigia.config import settings

logging.basicConfig(level=settings.LOG_LEVEL)

# ──────────────────────────────────────────────────────────────
# Carrega sempre o modelo “medium”; se houver GPU ele sobe em CUDA
# ──────────────────────────────────────────────────────────────
try:
    whisper_model = whisper.load_model(
        "medium",
        device="cuda" if torch.cuda.is_available() else "cpu"
    )
except Exception as e:
    logging.error("Falha ao carregar Whisper‑medium: %s", e)
    whisper_model = None


# ──────────────────────────────────────────────────────────────
def transcribe_audio_with_whisper(audio_data: bytes) -> str | None:
    """Transcreve bytes (.ogg, .mp3…) usando Whisper‑medium."""
    if whisper_model is None:
        logging.warning("Whisper não carregado; transcrição pulada.")
        return None

    path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_data)
            path = f.name

        result = whisper_model.transcribe(
            path,
            language="pt",
            word_timestamps=False,
            fp16=torch.cuda.is_available()
        )
        return result["text"].strip()

    except Exception as e:
        logging.error("Erro na transcrição Whisper: %s", e)
        return None

    finally:
        if path and os.path.exists(path):
            os.remove(path)
