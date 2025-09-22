import atexit
import faulthandler
import logging
import signal
import sys


def _log_unhandled(exc_type, exc, tb):
    logging.critical("UNHANDLED EXCEPTION", exc_info=(exc_type, exc, tb))


def _on_exit():
    logging.warning("Python atexit: processo encerrando.")


def _on_signal(signum, frame):
    try:
        sig = signal.Signals(signum).name
    except Exception:
        sig = str(signum)
    logging.critical("Sinal recebido: %s — dumping stacks…", sig)
    faulthandler.dump_traceback(all_threads=True, file=sys.stderr)


def install_crash_guard():
    # Tracebacks em falhas fatais
    faulthandler.enable(all_threads=True)
    # Permite acionar dump manual: kill -USR1 <pid>
    try:
        faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True)
    except Exception:
        pass
    # Loga exceções não tratadas
    sys.excepthook = _log_unhandled
    # Loga saída normal/forçada
    atexit.register(_on_exit)
    # Loga sinais comuns de término
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT):
        try:
            signal.signal(s, _on_signal)
        except Exception:
            pass
