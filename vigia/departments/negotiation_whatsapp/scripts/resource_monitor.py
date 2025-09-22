# -*- coding: utf-8 -*-
import logging
import os
import threading
import time
from typing import Dict, List, Tuple

try:
    import psutil
except Exception:
    psutil = None

_MB = 1024 * 1024


def _cpu_counts():
    phys = psutil.cpu_count(logical=False) if psutil else None
    logi = psutil.cpu_count(logical=True) if psutil else None
    return phys, logi


def _sample_thread_times(proc) -> Dict[int, float]:
    """Retorna {tid: cpu_time_total_em_segundos} para cada thread do processo."""
    out = {}
    for th in proc.threads():
        out[th.id] = float(th.user_time + th.system_time)
    return out


def _map_tid_to_pyname() -> Dict[int, str]:
    """Mapeia native_id -> thread.name (quando disponível)."""
    mapping = {}
    try:
        for t in threading.enumerate():
            nid = getattr(t, "native_id", None)
            if nid is not None:
                mapping[int(nid)] = t.name
    except Exception:
        pass
    return mapping


def _gpu_snapshot():
    # Loga VRAM via nvidia-smi se existir; silencioso se não houver NVIDIA.
    try:
        import subprocess

        out = (
            subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.total,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                timeout=2,
            )
            .decode()
            .strip()
            .splitlines()
        )
        for idx, line in enumerate(out):
            total, used = [int(x) for x in line.split(", ")]
            logging.info("[RES][GPU%d] VRAM=%dMiB/%dMiB", idx, used, total)
    except Exception:
        pass


def start_resource_monitor(
    interval_sec: float = 10.0, top_threads: int = 5, with_gpu: bool = False
):
    """
    Monitora o processo atual:
      - CPU do processo e do sistema
      - Núcleos físicos/lógicos
      - Memória RSS/VMS/USS
      - Threads OS vs Threads Python
      - Top N threads por consumo de CPU no intervalo
      - (Opcional) snapshot de GPU
    """
    if psutil is None:
        logging.warning("psutil não instalado; monitor desativado.")
        return

    proc = psutil.Process(os.getpid())
    phys, logi = _cpu_counts()
    logi = logi or 1  # evita divisão por zero

    # estado para cálculo de delta por thread
    prev_times = _sample_thread_times(proc)
    prev_wall = time.monotonic()

    # “prime” cpu_percent para dar leituras estáveis nas próximas chamadas
    _ = proc.cpu_percent(interval=None)
    _ = psutil.cpu_percent(interval=None)

    def _run():
        nonlocal prev_times, prev_wall  # <-- precisa vir antes de qualquer uso
        while True:
            try:
                time.sleep(interval_sec)

                now = time.monotonic()
                dt = max(1e-6, now - prev_wall)

                # CPU% do processo (média por core lógico) e do sistema
                cpu_proc = proc.cpu_percent(interval=None) / logi
                cpu_sys = psutil.cpu_percent(interval=None)

                # Memória
                mem = proc.memory_info()
                try:
                    mfull = proc.memory_full_info()
                    uss = getattr(mfull, "uss", 0) / _MB
                except Exception:
                    uss = 0.0

                # Threads / FDs
                threads_os = proc.num_threads()
                threads_py = len(threading.enumerate())
                fds = proc.num_fds() if hasattr(proc, "num_fds") else None

                logging.info(
                    "[RES] CPU(proc)=%.1f%% CPU(sys)=%.1f%% "
                    "| cores phys=%s log=%s "
                    "| RSS=%.1fMiB VMS=%.1fMiB USS=%.1fMiB "
                    "| threads os=%d py=%d fds=%s",
                    cpu_proc,
                    cpu_sys,
                    phys,
                    logi,
                    mem.rss / _MB,
                    mem.vms / _MB,
                    uss,
                    threads_os,
                    threads_py,
                    fds,
                )

                # Top N threads por consumo (em % de 1 núcleo no intervalo)
                curr_times = _sample_thread_times(proc)
                deltas: List[Tuple[float, int]] = []
                for tid, t_now in curr_times.items():
                    t_prev = prev_times.get(tid, t_now)
                    cpu_sec = max(0.0, t_now - t_prev)
                    cpu_pct_one_core = (cpu_sec / dt) * 100.0
                    if cpu_pct_one_core > 0.1:
                        deltas.append((cpu_pct_one_core, tid))
                deltas.sort(reverse=True)
                top = deltas[: max(0, top_threads)]

                name_by_tid = _map_tid_to_pyname()
                if top:
                    hot = []
                    for pct, tid in top:
                        tname = name_by_tid.get(tid, "unknown")
                        hot.append(f"{tid}:{tname}={pct:.1f}%")
                    logging.info("[RES] hot-threads (%% de 1 core): %s", ", ".join(hot))

                if with_gpu:
                    _gpu_snapshot()

                # avança estado
                prev_times = curr_times
                prev_wall = now

            except Exception as e:
                logging.debug("ResourceMonitor loop error: %s", e)

    th = threading.Thread(target=_run, name="ResourceMonitor", daemon=True)
    th.start()
