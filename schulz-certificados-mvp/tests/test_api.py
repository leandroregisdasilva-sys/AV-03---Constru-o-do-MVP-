"""Testes da API do serviço de metrologia (contrato HTTP + persistência)."""

from __future__ import annotations

import hashlib

import pytest

import gerar_exemplos as fab
from conftest import enviar



def test_health(api):
    r = api.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_openapi_publica_os_endpoints(api):
    caminhos = api.get("/openapi.json").json()["paths"]
    assert {"/v1/analises", "/v1/analises/{id_calibracao}", "/v1/modelo-planilha", "/health"} <= set(caminhos)



def test_planilha_aprovada_gera_parecer_aprovado(api, xlsx_aprovado):
    r = enviar(api, xlsx_aprovado)
    assert r.status_code == 201
    j = r.json()
    assert j["parecer"] == "APROVADO"
    assert j["resumo"]["total_pontos"] == 10 and j["resumo"]["fora_da_tolerancia"] == 0
    assert all(p["situacao"] == "DENTRO_DA_TOLERANCIA" for p in j["pontos"])


def test_planilha_reprovada_lista_os_pontos_fora(api, xlsx_reprovado):
    j = enviar(api, xlsx_reprovado).json()
    assert j["parecer"] == "REPROVADO"
    assert j["resumo"]["pontos_fora"] == ["DIAMETRO_B", "DIAMETRO_C"]
    por_nome = {p["ponto"]: p for p in j["pontos"]}
    assert por_nome["DIAMETRO_B"]["situacao"] == "FORA_DA_TOLERANCIA"
    assert por_nome["DIAMETRO_A"]["situacao"] == "DENTRO_DA_TOLERANCIA"


def test_valores_calculados_conferem_com_conta_manual(api, xlsx_aprovado):
    """DIAMETRO_A: leituras 10,0021 / 10,0027 / 10,0024 contra padrão 10,000."""
    p = next(x for x in enviar(api, xlsx_aprovado).json()["pontos"] if x["ponto"] == "DIAMETRO_A")
    assert p["media"] == pytest.approx((10.0021 + 10.0027 + 10.0024) / 3, abs=1e-12)
    assert p["erro_sistematico"] == pytest.approx(p["media"] - 10.0, abs=1e-12)
    assert p["erro_absoluto"] == pytest.approx(abs(p["erro_sistematico"]), abs=1e-12)
    assert p["lea_aplicado"] == 0.010


def test_ponto_no_limite_exato_e_aprovado(api, xlsx_aprovado):
    p = next(x for x in enviar(api, xlsx_aprovado).json()["pontos"] if x["ponto"] == "LIMITE_EXATO")
    assert p["situacao"] == "DENTRO_DA_TOLERANCIA"


def test_registra_hash_e_formato_do_arquivo(api, xlsx_aprovado):
    j = enviar(api, xlsx_aprovado, "minha.xlsx").json()
    assert j["arquivo"]["nome"] == "minha.xlsx"
    assert j["arquivo"]["sha256"] == hashlib.sha256(xlsx_aprovado).hexdigest()
    assert j["arquivo"]["formato"] == "tabela_de_leituras"


def test_calypso_e_aceito_ponta_a_ponta(api):
    dados = fab.calypso([fab.BLOCO_CALYPSO_1, fab.BLOCO_CALYPSO_2])
    j = enviar(api, dados).json()
    assert j["arquivo"]["formato"] == "calypso_report" and j["resumo"]["total_pontos"] == 6
    assert j["parecer"] == "APROVADO"



def test_analise_e_gravada_e_pode_ser_consultada(api, xlsx_reprovado):
    criada = enviar(api, xlsx_reprovado).json()
    lida = api.get(f"/v1/analises/{criada['id_calibracao']}")
    assert lida.status_code == 200
    assert lida.json()["parecer"] == "REPROVADO"
    assert lida.json()["pontos"] == criada["pontos"]


def test_listagem_mais_recentes_primeiro_e_paginada(api, xlsx_aprovado, xlsx_reprovado):
    a = enviar(api, xlsx_aprovado).json()["id_calibracao"]
    b = enviar(api, xlsx_reprovado).json()["id_calibracao"]
    lista = api.get("/v1/analises").json()
    assert lista["total"] == 2 and [i["id_calibracao"] for i in lista["itens"]] == [b, a]
    pag = api.get("/v1/analises", params={"limite": 1, "deslocamento": 1}).json()
    assert [i["id_calibracao"] for i in pag["itens"]] == [a]


def test_consulta_inexistente_devolve_404(api):
    r = api.get("/v1/analises/999")
    assert r.status_code == 404 and r.json()["erro"]["codigo"] == "NAO_ENCONTRADO"


def test_limite_invalido_na_listagem_e_422(api):
    assert api.get("/v1/analises", params={"limite": 0}).status_code == 422


def test_dados_sobrevivem_a_reinicio_do_servico(tmp_path, xlsx_reprovado):
    from fastapi.testclient import TestClient
    from metrologia_service.main import criar_app

    caminho = str(tmp_path / "persistente.db")
    id_ = enviar(TestClient(criar_app(caminho)), xlsx_reprovado).json()["id_calibracao"]
    novo = TestClient(criar_app(caminho))  # "reinício": nova instância, mesmo arquivo
    assert novo.get(f"/v1/analises/{id_}").json()["parecer"] == "REPROVADO"


def test_analise_invalida_nao_grava_nada(api):
    enviar(api, b"isto nao e um xlsx", "x.xlsx")
    assert api.get("/v1/analises").json()["total"] == 0



def test_arquivo_nao_zip_devolve_400(api):
    r = enviar(api, b"lixo", "x.xlsx")
    assert r.status_code == 400 and r.json()["erro"]["codigo"]


def test_extensao_nao_suportada_devolve_erro_claro(api):
    r = enviar(api, b"a,b\n1,2", "dados.csv")
    assert r.status_code in (400, 415, 422) and r.json()["erro"]["mensagem"]


def test_arquivo_vazio_devolve_400(api):
    r = enviar(api, b"", "vazio.xlsx")
    assert r.status_code == 400 and r.json()["erro"]["codigo"] == "ARQUIVO_INVALIDO"


def test_arquivo_maior_que_5mb_devolve_413(api):
    r = enviar(api, b"0" * (5 * 1024 * 1024 + 10), "grande.xlsx")
    assert r.status_code == 413 and r.json()["erro"]["codigo"] == "ARQUIVO_GRANDE"


def test_requisicao_sem_arquivo_devolve_422_no_contrato(api):
    r = api.post("/v1/analises")
    assert r.status_code == 422 and r.json()["erro"]["codigo"] == "REQUISICAO_INVALIDA"


def test_planilha_sem_cabecalho_devolve_422(api):
    from openpyxl import Workbook
    import io

    wb = Workbook()
    wb.active.append(["nada", "util", "aqui"])
    buf = io.BytesIO()
    wb.save(buf)
    r = enviar(api, buf.getvalue(), "vazia.xlsx")
    assert r.status_code == 422 and r.json()["erro"]["detalhes"] is not None


def test_modelo_de_planilha_baixado_e_processado_de_volta(api):
    """O modelo oferecido ao usuário precisa ser aceito pelo próprio sistema."""
    r = api.get("/v1/modelo-planilha")
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    assert r.content[:2] == b"PK"
    devolvida = enviar(api, r.content, "modelo.xlsx")
    assert devolvida.status_code == 201 and devolvida.json()["parecer"] in ("APROVADO", "REPROVADO")
