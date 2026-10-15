"""Testes da interface web (renderização e integração com a API, sem rede)."""

from __future__ import annotations

import io

import pytest

from conftest import enviar


def enviar_web(web, dados: bytes, nome: str = "planilha.xlsx"):
    return web.post("/analisar", files={"arquivo": (nome, io.BytesIO(dados), "application/octet-stream")})


def test_pagina_inicial_tem_formulario_de_upload(web):
    r = web.get("/")
    assert r.status_code == 200
    assert 'type="file"' in r.text and 'action="/analisar"' in r.text


def test_upload_aprovado_redireciona_e_mostra_parecer_verde(web, xlsx_aprovado):
    r = enviar_web(web, xlsx_aprovado)
    assert r.status_code == 303 and r.headers["location"].startswith("/analises/")
    pagina = web.get(r.headers["location"])
    assert pagina.status_code == 200
    assert "PARECER FINAL: INSTRUMENTO APROVADO" in pagina.text
    assert 'class="parecer aprovado"' in pagina.text
    assert pagina.text.count("DENTRO_DA_TOLERANCIA") >= 10


def test_upload_reprovado_mostra_parecer_vermelho_e_pontos_fora(web, xlsx_reprovado):
    r = enviar_web(web, xlsx_reprovado)
    pagina = web.get(r.headers["location"]).text
    assert "PARECER FINAL: INSTRUMENTO REPROVADO" in pagina
    assert 'class="parecer reprovado"' in pagina
    assert "FORA_DA_TOLERANCIA" in pagina and "DIAMETRO_B" in pagina


def test_resultado_usa_virgula_decimal_ptbr(web, xlsx_aprovado):
    pagina = web.get(enviar_web(web, xlsx_aprovado).headers["location"]).text
    assert "10,0024" in pagina  # média de DIAMETRO_A


def test_planilha_invalida_mostra_mensagem_na_propria_tela(web):
    r = enviar_web(web, b"lixo", "ruim.xlsx")
    assert r.status_code == 400
    assert "ruim.xlsx" in r.text or "inválid" in r.text.lower() or "arquivo" in r.text.lower()
    assert 'type="file"' in r.text  # usuário pode tentar de novo


def test_historico_lista_as_analises(web, xlsx_aprovado, xlsx_reprovado):
    enviar_web(web, xlsx_aprovado)
    enviar_web(web, xlsx_reprovado)
    h = web.get("/historico")
    assert h.status_code == 200
    assert "APROVADO" in h.text and "REPROVADO" in h.text


def test_historico_vazio_nao_quebra(web):
    assert web.get("/historico").status_code == 200


def test_analise_inexistente_mostra_404_amigavel(web):
    r = web.get("/analises/12345")
    assert r.status_code == 404 and "não encontrada" in r.text.lower()


def test_download_do_modelo(web):
    r = web.get("/modelo")
    assert r.status_code == 200 and r.content[:2] == b"PK"


def test_saude_reflete_a_api(web):
    r = web.get("/saude")
    assert r.status_code == 200 and r.json()["metrologia"] == "ok"


def test_servico_de_metrologia_fora_do_ar_gera_503_amigavel():
    from web_ui.main import criar_app
    from fastapi.testclient import TestClient

    
    cli = TestClient(criar_app("http://127.0.0.1:9"), follow_redirects=False)
    assert cli.get("/saude").status_code == 503
    assert cli.get("/historico").status_code == 503
    r = enviar_web(cli, b"x")
    assert r.status_code == 503 and "indispon" in r.text.lower()


def test_arquivos_estaticos_sao_servidos(web):
    assert web.get("/static/style.css").status_code == 200
