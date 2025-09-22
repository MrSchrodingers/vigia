# -*- coding: utf-8 -*-
"""
Cliente para o whisper_worker (subprocesso).
- Garante isolamento contra segfaults.
- Formata resposta com tag de CONFIDÊNCIA igual ao código anterior.
- Respeita semáforo de concorrência via settings.WPP_MAX_WHISPER_CONCURRENCY.
"""

import base64
import json
import logging
import os
import subprocess
import sys
import threading
import time
from threading import Semaphore
from typing import Optional

from vigia.config import settings

logging.basicConfig(level=settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

# Limite de concorrência (mantém compatibilidade com seu código)
WHISPER_SEMAPHORE = Semaphore(getattr(settings, "WPP_MAX_WHISPER_CONCURRENCY", 1))
# Caminho/forma de invocar o worker (usa -m para evitar problemas de path)
WORKER_MODULE = "vigia.tasks.whisper_worker"
WORKER_CMD = [sys.executable, "-u", "-m", WORKER_MODULE]

# Tempo máximo de uma transcrição (segundos)
TRANSCRIBE_TIMEOUT = int(os.getenv("WHISPER_CLIENT_TIMEOUT", "120"))


class WhisperSubprocessClient:
    """
    Cliente de linha única (seq.) com lock — o semáforo externo controla o paralelismo.
    Reinicia o worker automaticamente se morrer.
    """

    def __init__(self, cmd=None):
        self.cmd = cmd or WORKER_CMD
        self._lock = threading.Lock()
        self._start()

    def _start(self):
        env = os.environ.copy()
        # Garante limites de threads no worker também
        env.setdefault("OMP_NUM_THREADS", "1")
        env.setdefault("OPENBLAS_NUM_THREADS", "1")
        env.setdefault("MKL_NUM_THREADS", "1")
        env.setdefault("NUMEXPR_NUM_THREADS", "1")
        env.setdefault("TOKENIZERS_PARALLELISM", "false")
        env.setdefault("FFMPEG_THREADS", "1")

        self.p = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,  # logs vão para stderr do processo atual
            text=True,
            bufsize=1,
            env=env,
        )
        # Handshake rápido (ping)
        try:
            self._write_json({"cmd": "ping"})
            pong = self._read_line(timeout=5.0)
            if not pong or not json.loads(pong).get("pong"):
                raise RuntimeError("No pong from whisper worker")
            logger.info("whisper_worker pronto (pid=%s)", self.p.pid)
        except Exception as e:
            logger.error("Falha no handshake do whisper_worker: %s", e)
            try:
                self.p.kill()
            except Exception:
                pass
            raise

    def _write_json(self, obj: dict):
        line = json.dumps(obj, ensure_ascii=False) + "\n"
        assert self.p.stdin is not None
        self.p.stdin.write(line)
        self.p.stdin.flush()

    def _read_line(self, timeout: float) -> Optional[str]:
        """
        Leitura com timeout simples: poll até ter uma linha.
        """
        end = time.monotonic() + timeout
        so = self.p.stdout
        assert so is not None
        while time.monotonic() < end:
            line = so.readline()
            if line:
                return line.strip()
            # worker morreu?
            if self.p.poll() is not None:
                return None
            time.sleep(0.01)
        return None

    def ensure_alive(self):
        if self.p.poll() is not None:
            logger.warning("whisper_worker morto; reiniciando…")
            self._start()

    def transcribe_b64(self, b64: str, timeout: float) -> dict:
        with self._lock:
            self.ensure_alive()
            self._write_json({"b64": b64})
            line = self._read_line(timeout=timeout)
        if not line:
            raise RuntimeError("Sem resposta do whisper_worker")
        try:
            resp = json.loads(line)
        except Exception as e:
            raise RuntimeError(f"Resposta inválida do whisper_worker: {e}") from e
        return resp


# Instância global única (processo atual)
_worker_client = WhisperSubprocessClient()


def transcribe_audio_with_whisper(audio_data: bytes) -> str | None:
    """
    Mantém a mesma assinatura/semântica anterior.
    Devolve:
      - "[ÁUDIO VAZIO]" | "[ÁUDIO CORROMPIDO]" | "[ÁUDIO ERRO GPU OOM]" | "[ÁUDIO TRANSCRIÇÃO FALHOU]"
      - ou "[ÁUDIO CONFIDÊNCIA=0.87]: <texto>"
    """
    if not audio_data or len(audio_data) < 256:
        return "[ÁUDIO VAZIO]"

    b64 = base64.b64encode(audio_data).decode()

    logger.debug(
        "Whisper aguardando slot... (semáforo=%s)",
        getattr(settings, "WPP_MAX_WHISPER_CONCURRENCY", 1),
    )
    with WHISPER_SEMAPHORE:
        try:
            resp = _worker_client.transcribe_b64(b64, timeout=TRANSCRIBE_TIMEOUT)
        except Exception as e:
            logger.error("Falha ao chamar whisper_worker: %s", e)
            return "[ÁUDIO TRANSCRIÇÃO FALHOU]"

    if not resp.get("ok"):
        # Converter alguns erros em tags conhecidas (compatibilidade com seu pipeline)
        err = (resp.get("err") or "").lower()
        if "cannot reshape tensor of 0 elements" in err:
            return "[ÁUDIO VAZIO]"
        if "linear(in_features=" in err:
            return "[ÁUDIO CORROMPIDO]"
        if "oom" in err or "out of memory" in err:
            return "[ÁUDIO ERRO GPU OOM]"
        return "[ÁUDIO TRANSCRIÇÃO FALHOU]"

    text = (resp.get("text") or "").strip()
    conf = float(resp.get("conf") or 0.0)

    # Se já for uma tag especial, devolve como está
    if text.startswith("[ÁUDIO"):
        return text

    # Mantém padrão anterior com CONFIDÊNCIA
    return f"[ÁUDIO CONFIDÊNCIA={conf:.2f}]: {text}"
