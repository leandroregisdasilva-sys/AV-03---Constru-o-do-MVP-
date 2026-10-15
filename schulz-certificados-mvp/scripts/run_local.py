"""Sobe os dois microsserviços localmente (sem Docker).

    python scripts/run_local.py

  * Serviço de metrologia (API):  http://127.0.0.1:8001   (docs: /docs)
  * Interface web:                http://127.0.0.1:8000

Variáveis opcionais: METROLOGIA_DB (arquivo SQLite), PORTA_API, PORTA_WEB.
Encerre com Ctrl+C.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def main() -> int:
    porta_api = os.environ.get("PORTA_API", "8001")
    porta_web = os.environ.get("PORTA_WEB", "8000")
    ambiente = {**os.environ, "METROLOGIA_URL": f"http://127.0.0.1:{porta_api}"}
    ambiente.setdefault("METROLOGIA_DB", str(RAIZ / "data" / "metrologia.db"))
    comandos = [
        ([sys.executable, "-m", "uvicorn", "metrologia_service.main:app", "--port", porta_api],
         RAIZ / "services" / "metrologia"),
        ([sys.executable, "-m", "uvicorn", "web_ui.main:app", "--port", porta_web],
         RAIZ / "services" / "web"),
    ]
    processos = [subprocess.Popen(cmd, cwd=cwd, env=ambiente) for cmd, cwd in comandos]
    print(f"\n>> Interface web: http://127.0.0.1:{porta_web}   |   API: http://127.0.0.1:{porta_api}/docs\n")

    def encerrar(*_: object) -> None:
        for p in processos:
            p.terminate()

    signal.signal(signal.SIGINT, encerrar)
    signal.signal(signal.SIGTERM, encerrar)
    try:
        while all(p.poll() is None for p in processos):
            time.sleep(0.5)
    finally:
        encerrar()
        for p in processos:
            p.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
