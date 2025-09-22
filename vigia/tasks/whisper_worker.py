# -*- coding: utf-8 -*-
"""
Worker de transcrição Whisper rodando em subprocesso.
- Lê JSON por stdin (uma linha por requisição).
- Escreve JSON por stdout (uma linha por resposta).
- NÃO escreve logs em stdout (apenas stderr), para não poluir o protocolo.
- Limita threads de BLAS/Torch e desabilita MKLDNN para evitar segfaults.
- Valida áudio antes de transcrever (frames > 0 / não-zeros suficientes).
Protocolo (entrada):
  {"b64": "<base64 do áudio .ogg>", "opts": {...opcional...}}
Protocolo (saída):
  {"ok": true, "text": "<texto ou tag>", "conf": 0.0..1.0}
  {"ok": false, "err": "<mensagem de erro>"}
"""

import json
import math
import os
import signal
import sys
import tempfile
from base64 import b64decode

# ── Limites de threads DEVEM vir antes dos imports pesados ────────────────────
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("FFMPEG_THREADS", "1")  # se usado

# ── Imports pesados ───────────────────────────────────────────────────────────
import numpy as np  # noqa: E402
import torch  # noqa: E402
import whisper  # noqa: E402

# ── Torch tuning para CPU estável ────────────────────────────────────────────
try:
    torch.backends.mkldnn.enabled = False
except Exception:
    pass

try:
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
except Exception:
    pass

# ── Logging só em STDERR (não poluir stdout do protocolo) ─────────────────────
import logging  # noqa: E402

logging.basicConfig(level=os.getenv("WHISPER_WORKER_LOGLEVEL", "WARNING"))
logger = logging.getLogger("whisper_worker")

# ── Flags/Config ──────────────────────────────────────────────────────────────
MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
FORCE_CPU = os.getenv("WHISPER_FORCE_CPU", "0") == "1"
DEVICE = "cpu" if FORCE_CPU else ("cuda" if torch.cuda.is_available() else "cpu")

# ── Carregamento do modelo ────────────────────────────────────────────────────
try:
    model = whisper.load_model(MODEL_NAME, device=DEVICE)
    logger.warning("Whisper worker carregado: model=%s device=%s", MODEL_NAME, DEVICE)
except Exception as e:
    logger.exception("Falha ao carregar Whisper: %s", e)
    print(json.dumps({"ok": False, "err": f"load_model: {e}"}), flush=True)
    sys.exit(2)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _classify_exception_text(s: str) -> str:
    s = (s or "").lower()
    if "cannot reshape tensor of 0 elements" in s:
        return "AUDIO_VAZIO"
    if "out of memory" in s:
        return "OOM_GPU"
    if "linear(in_features=" in s:
        return "AUDIO_CORROMPIDO"
    if "nan" in s and "logits" in s:
        return "AUDIO_NAN"
    return "DESCONHECIDO"


def _confidence_from_segments(segments) -> float:
    if not segments:
        return 0.0
    avg_lp = sum((seg.get("avg_logprob", -5.0) or -5.0) for seg in segments) / max(
        1, len(segments)
    )
    # mapeia logprob médio para [0,1] de forma simples (mesma ideia que você usava)
    return max(0.0, min(math.exp(avg_lp), 1.0))


def _load_audio_frames_ok(path: str) -> bool:
    """
    Usa whisper.load_audio (ffmpeg) para validar se há frames (>0) e se não é ~tudo zero.
    """
    try:
        audio = whisper.load_audio(path)  # float32, 16000Hz
        if audio is None or audio.size == 0:
            return False
        if not np.any(np.isfinite(audio)):
            return False
        nz = np.count_nonzero(np.abs(audio) > 1e-8)
        ratio = nz / audio.size
        return ratio > 0.001
    except Exception as e:
        logger.debug("Validação de áudio falhou: %s", e)
        return False


TRANSCRIBE_DEFAULT_OPTS = dict(
    language="pt",
    word_timestamps=False,
    task="transcribe",
    condition_on_previous_text=False,
    temperature=0,
    no_speech_threshold=0.6,
    logprob_threshold=-1.0,
    compression_ratio_threshold=2.4,
)


def _transcribe_bytes(b: bytes, opts: dict | None = None) -> tuple[str, float]:
    """
    Retorna (text_or_tag, conf) onde text_or_tag pode ser "[ÁUDIO VAZIO]" etc.
    """
    if not b or len(b) < 256:
        return "[ÁUDIO VAZIO]", 0.0

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
        f.write(b)
        path = f.name

    try:
        if not _load_audio_frames_ok(path):
            return "[ÁUDIO VAZIO]", 0.0

        options = {**TRANSCRIBE_DEFAULT_OPTS, **(opts or {})}
        with torch.inference_mode():
            res = model.transcribe(path, fp16=(DEVICE == "cuda"), **options)

        text = (res.get("text") or "").strip()
        conf = _confidence_from_segments(res.get("segments") or [])
        if not text:
            return "[ÁUDIO]: (silêncio ou inaudível)", conf
        return text, conf

    except Exception as e:
        cls = _classify_exception_text(str(e))
        logger.error("Falha na transcrição (%s): %s", cls, e)
        if cls == "AUDIO_VAZIO":
            return "[ÁUDIO VAZIO]", 0.0
        if cls == "AUDIO_CORROMPIDO":
            return "[ÁUDIO CORROMPIDO]", 0.0
        if cls == "OOM_GPU":
            return "[ÁUDIO ERRO GPU OOM]", 0.0
        return "[ÁUDIO TRANSCRIÇÃO FALHOU]", 0.0
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


# ── Sinais para encerramento limpo ────────────────────────────────────────────
def _term(_signo, _frame):
    logger.warning("Sinal recebido; encerrando worker.")
    sys.exit(0)


for _sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT):
    try:
        signal.signal(_sig, _term)
    except Exception:
        pass


# ── Loop principal de mensagens ───────────────────────────────────────────────
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except Exception as e:
        print(json.dumps({"ok": False, "err": f"bad_json: {e}"}), flush=True)
        continue

    # Comandos simples
    if req.get("cmd") == "ping":
        print(json.dumps({"ok": True, "pong": True}), flush=True)
        continue

    try:
        b64 = req["b64"]
        opts = req.get("opts") or {}
        audio = b64decode(b64)
        text, conf = _transcribe_bytes(audio, opts)
        print(json.dumps({"ok": True, "text": text, "conf": float(conf)}), flush=True)
    except Exception as e:
        print(json.dumps({"ok": False, "err": str(e)}), flush=True)

# EOF stdin: encerra
sys.exit(0)
