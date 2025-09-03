import whisper
import torch
import tempfile
import os
import logging
from vigia.config import settings
import math 

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
def _confidence_from_segments(segments):
    """
    Calcula uma confiança ∈ [0,1] a partir do avg_logprob médio dos segmentos.
    Whisper devolve valores negativos (≈0→muito confiável, ≈‑5→ruim).
    """
    if not segments:
        return 0.0
    avg_lp = sum(s["avg_logprob"] for s in segments) / len(segments)
    # converte log‑prob média em prob. grosseira e corta nos extremos
    return max(0.0, min(math.exp(avg_lp), 1.0))

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
        conf     = _confidence_from_segments(result.get("segments", []))
        conf_tag = f"CONFIDÊNCIA={conf:.2f}"
        return f"[ÁUDIO {conf_tag}]: {result['text'].strip()}"

    except Exception as e:
        logging.error("Erro na transcrição Whisper: %s", e)
        return None

    finally:
        if path and os.path.exists(path):
            os.remove(path)
