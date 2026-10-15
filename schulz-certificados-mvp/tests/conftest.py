from __future__ import annotations

import io
import warnings

import httpx
import pytest
from fastapi.testclient import TestClient

import gerar_exemplos as fab
from metrologia_service.main import criar_app as criar_api
from web_ui.main import criar_app as criar_web

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")


@pytest.fixture()
def api(tmp_path):
    """Serviço de metrologia com banco SQLite temporário."""
    return TestClient(criar_api(str(tmp_path / "teste.db")))


@pytest.fixture()
def api_app(tmp_path):
    return criar_api(str(tmp_path / "web.db"))


@pytest.fixture()
def web(api_app):
    """Interface web ligada ao serviço de metrologia em memória (sem rede)."""
    transporte = httpx.ASGITransport(app=api_app)
    return TestClient(criar_web("http://metrologia.local", transporte), follow_redirects=False)


@pytest.fixture()
def xlsx_aprovado() -> bytes:
    return fab.tabela_simples(fab.PONTOS_APROVADO)


@pytest.fixture()
def xlsx_reprovado() -> bytes:
    return fab.tabela_simples(fab.PONTOS_REPROVADO)


def enviar(cliente: TestClient, dados: bytes, nome: str = "planilha.xlsx"):
    return cliente.post("/v1/analises", files={"arquivo": (nome, io.BytesIO(dados), "application/octet-stream")})
