"""Teste ponta a ponta: sobe os DOIS microsserviços de verdade (uvicorn, HTTP real).

    pytest -m e2e
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

import gerar_exemplos as fab

RAIZ = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.e2e


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _esperar(url: str, tentativas: int = 80) -> None:
    for _ in range(tentativas):
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"serviço não respondeu em {url}")


@pytest.fixture(scope="module")
def sistema(tmp_path_factory):
    banco = tmp_path_factory.mktemp("e2e") / "e2e.db"
    p_api, p_web = _porta_livre(), _porta_livre()
    env = {**os.environ, "METROLOGIA_DB": str(banco), "METROLOGIA_URL": f"http://127.0.0.1:{p_api}"}
    cmd = lambda mod, porta: [sys.executable, "-m", "uvicorn", mod, "--port", str(porta), "--log-level", "warning"]
    procs = [
        subprocess.Popen(cmd("metrologia_service.main:app", p_api), cwd=RAIZ / "services/metrologia", env=env),
        subprocess.Popen(cmd("web_ui.main:app", p_web), cwd=RAIZ / "services/web", env=env),
    ]
    api, web = f"http://127.0.0.1:{p_api}", f"http://127.0.0.1:{p_web}"
    try:
        _esperar(f"{api}/health")
        _esperar(f"{web}/saude")
        yield api, web
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            p.wait(timeout=10)


def test_fluxo_completo_pela_interface_web(sistema):
    api, web = sistema
    dados = fab.tabela_simples(fab.PONTOS_REPROVADO)
    r = httpx.post(f"{web}/analisar", files={"arquivo": ("reprovado.xlsx", dados)}, follow_redirects=True, timeout=30)
    assert r.status_code == 200
    assert "PARECER FINAL: INSTRUMENTO REPROVADO" in r.text and "FORA_DA_TOLERANCIA" in r.text
    id_ = int(str(r.url).rstrip("/").split("/")[-1])
    j = httpx.get(f"{api}/v1/analises/{id_}").json()
    assert j["parecer"] == "REPROVADO" and j["resumo"]["pontos_fora"] == ["DIAMETRO_B", "DIAMETRO_C"]


def test_fluxo_aprovado_e_historico(sistema):
    _, web = sistema
    dados = fab.tabela_simples(fab.PONTOS_APROVADO)
    r = httpx.post(f"{web}/analisar", files={"arquivo": ("aprovado.xlsx", dados)}, follow_redirects=True, timeout=30)
    assert "PARECER FINAL: INSTRUMENTO APROVADO" in r.text
    assert "aprovado.xlsx" in httpx.get(f"{web}/historico").text


def test_erro_de_planilha_chega_ao_usuario(sistema):
    _, web = sistema
    r = httpx.post(f"{web}/analisar", files={"arquivo": ("ruim.xlsx", b"nao e xlsx")}, timeout=30)
    assert r.status_code == 400
