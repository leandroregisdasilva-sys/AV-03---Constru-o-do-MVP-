"""Gera os prints de evidência do funcionamento da aplicação.

Sobe os dois serviços com um banco temporário, usa um navegador de verdade
(Playwright/Chromium) para fazer o upload das planilhas pela interface e salva
as capturas de tela em ``docs/evidencias/``.

    pip install -r requirements-dev.txt && playwright install chromium
    python scripts/capturar_evidencias.py [--saida docs/evidencias] [--arquivos pasta]

Com ``--arquivos`` usa as planilhas .xlsx da pasta indicada (ex.: planilhas reais,
guardadas FORA do repositório); sem ela, usa as planilhas fictícias de ``exemplos/``.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

RAIZ = Path(__file__).resolve().parent.parent


def porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def esperar(url: str) -> None:
    for _ in range(80):
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"sem resposta em {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", default=str(RAIZ / "docs" / "evidencias"))
    ap.add_argument("--arquivos", default=str(RAIZ / "exemplos"))
    args = ap.parse_args()
    saida = Path(args.saida)
    saida.mkdir(parents=True, exist_ok=True)
    planilhas = sorted(Path(args.arquivos).glob("*.xlsx"))
    if not planilhas:
        sys.exit("nenhuma planilha .xlsx encontrada")

    tmp = tempfile.mkdtemp()
    p_api, p_web = porta_livre(), porta_livre()
    env = {**os.environ, "METROLOGIA_DB": str(Path(tmp) / "evid.db"),
           "METROLOGIA_URL": f"http://127.0.0.1:{p_api}"}
    cmd = lambda mod, porta: [sys.executable, "-m", "uvicorn", mod, "--port", str(porta), "--log-level", "warning"]
    procs = [subprocess.Popen(cmd("metrologia_service.main:app", p_api), cwd=RAIZ / "services/metrologia", env=env),
             subprocess.Popen(cmd("web_ui.main:app", p_web), cwd=RAIZ / "services/web", env=env)]
    web, api = f"http://127.0.0.1:{p_web}", f"http://127.0.0.1:{p_api}"
    try:
        esperar(f"{api}/health")
        esperar(f"{web}/saude")
        with sync_playwright() as p:
            nav = p.chromium.launch()
            pg = nav.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(web + "/")
            pg.screenshot(path=saida / "01_tela_inicial.png")
            for i, arq in enumerate(planilhas, start=1):
                pg.goto(web + "/")
                pg.set_input_files("#arquivo", str(arq))
                pg.screenshot(path=saida / f"02_{i:02d}_arquivo_selecionado.png") if i == 1 else None
                pg.click("#enviar")
                pg.wait_for_url("**/analises/*")
                pg.screenshot(path=saida / f"03_{i:02d}_resultado_{arq.stem}.png", full_page=True)
            pg.goto(web + "/historico")
            pg.screenshot(path=saida / "04_historico.png", full_page=True)
            # erro tratado: arquivo que não é planilha
            falso = Path(tmp) / "nao_e_planilha.xlsx"
            falso.write_bytes(b"isto nao e um xlsx")
            pg.goto(web + "/")
            pg.set_input_files("#arquivo", str(falso))
            pg.click("#enviar")
            pg.wait_for_selector(".alerta")
            pg.screenshot(path=saida / "05_erro_arquivo_invalido.png", full_page=True)
            # resposta JSON da API (o /docs do Swagger carrega scripts de um CDN e
            # exige internet; o JSON abaixo funciona offline)
            pg2 = nav.new_page(viewport={"width": 1100, "height": 900})
            pg2.goto(api + "/v1/analises/1")
            pg2.screenshot(path=saida / "06_api_resposta_json.png")
            nav.close()
        print("Capturas salvas em", saida)
    finally:
        for pr in procs:
            pr.terminate()
        for pr in procs:
            pr.wait(timeout=10)


if __name__ == "__main__":
    main()
