"""Serviço de Metrologia — API REST.

Recebe planilhas .xlsx, aplica as regras metrológicas e persiste o resultado.
Documentação interativa (OpenAPI/Swagger): ``/docs``.
"""

from __future__ import annotations

import hashlib
import math

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from . import __versao__
from .calculo import ErroCalculo, analisar
from .ingestao import ErroPlanilha, ler_planilha, validar_nome_arquivo
from .modelo import gerar_modelo_xlsx
from .repositorio import Repositorio
from .schemas import (AnaliseOut, ErroOut, ListaAnalisesOut, SaudeOut)

TAMANHO_MAXIMO = 5 * 1024 * 1024  
MEDIA_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

RESPOSTAS_ERRO = {
    400: {"model": ErroOut, "description": "Arquivo ilegível ou formato não suportado"},
    413: {"model": ErroOut, "description": "Arquivo maior que 5 MB"},
    422: {"model": ErroOut, "description": "Planilha sem layout reconhecido ou com dados incompletos"},
}


def _montar(registro: dict) -> dict:
    """Converte a linha do banco no contrato AnaliseOut."""
    pontos = registro["pontos"]
    fora = [p["ponto"] for p in pontos if p["situacao"] == "FORA_DA_TOLERANCIA"]
    return {
        "id_calibracao": registro["id_calibracao"],
        "criado_em": registro["criado_em"],
        "parecer": registro["resultado_geral"],
        "arquivo": {"nome": registro["arquivo_nome"], "sha256": registro["arquivo_sha256"],
                    "formato": registro["formato"], "aba": registro["aba"]},
        "metadados": {c: registro[c] for c in (
            "cliente", "tecnico", "codigo_instrumento", "denominacao", "fabricante",
            "data_calibracao", "temperatura_ambiente", "plano_medicao", "padrao_utilizado")},
        "resumo": {
            "total_pontos": len(pontos),
            "dentro_da_tolerancia": len(pontos) - len(fora),
            "fora_da_tolerancia": len(fora),
            "pontos_fora": fora,
            "maior_desvio_padrao": max(p["desvio_padrao"] for p in pontos),
            "maior_erro_absoluto": max(p["erro_absoluto"] for p in pontos),
        },
        "pontos": [{k: p[k] for k in (
            "sequencia", "ponto", "valor_padrao", "lea_positivo", "lea_negativo", "leituras",
            "media", "desvio_padrao", "erro_sistematico", "erro_absoluto", "lea_aplicado",
            "limite_minimo", "limite_maximo", "situacao")} for p in pontos],
        "avisos": registro["avisos"],
    }


def _erro(status: int, codigo: str, mensagem: str, detalhes: list[str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status,
                        content={"erro": {"codigo": codigo, "mensagem": mensagem,
                                          "detalhes": detalhes or []}})


def criar_app(caminho_db: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Serviço de Metrologia – Schulz",
        version=__versao__,
        description=(
            "Ingestão de planilhas Excel e cálculo metrológico (média, erro sistemático, "
            "validação por LEA e parecer final) para o MVP de automação de certificados "
            "de calibração. Projeto Aplicado III – Grupo 45."
        ),
    )
    app.state.caminho_db = caminho_db
    app.state.repositorio = None

    def repo() -> Repositorio:
        if app.state.repositorio is None:
            app.state.repositorio = Repositorio(app.state.caminho_db)
        return app.state.repositorio

    @app.exception_handler(ErroPlanilha)
    async def _erro_planilha(_: Request, exc: ErroPlanilha) -> JSONResponse:
        return _erro(exc.status, exc.codigo, exc.mensagem, exc.detalhes)

    @app.exception_handler(ErroCalculo)
    async def _erro_calculo(_: Request, exc: ErroCalculo) -> JSONResponse:
        return _erro(422, "DADOS_INVALIDOS", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _erro_requisicao(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _erro(422, "REQUISICAO_INVALIDA",
                     "Requisição inválida: envie o arquivo no campo multipart 'arquivo'.",
                     [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()])

    @app.get("/health", response_model=SaudeOut, tags=["infraestrutura"])
    def saude() -> dict:
        repo()  
        return {"status": "ok", "servico": "metrologia", "versao": __versao__}

    @app.post("/v1/analises", response_model=AnaliseOut, status_code=201,
              responses=RESPOSTAS_ERRO, tags=["análises"],
              summary="Processa uma planilha e emite o parecer")
    def criar_analise(arquivo: UploadFile = File(..., description="Planilha .xlsx com leituras e valores do padrão")):
        nome = validar_nome_arquivo(arquivo.filename)
        dados = arquivo.file.read(TAMANHO_MAXIMO + 1)
        if len(dados) > TAMANHO_MAXIMO:
            return _erro(413, "ARQUIVO_GRANDE", "O arquivo excede o limite de 5 MB.")
        if not dados:
            return _erro(400, "ARQUIVO_INVALIDO", "O arquivo enviado está vazio.")
        planilha = ler_planilha(dados, nome)
        resultado = analisar(planilha.pontos, planilha.avisos)
        id_cal = repo().salvar(
            arquivo_nome=nome, arquivo_sha256=hashlib.sha256(dados).hexdigest(),
            formato=planilha.formato, aba=planilha.aba, metadados=planilha.metadados,
            analise=resultado)
        return _montar(repo().obter(id_cal))

    @app.get("/v1/analises", response_model=ListaAnalisesOut, tags=["análises"],
             summary="Lista as análises já processadas (mais recentes primeiro)")
    def listar(limite: int = Query(50, ge=1, le=200), deslocamento: int = Query(0, ge=0)):
        total, itens = repo().listar(limite, deslocamento)
        return {"total": total, "limite": limite, "deslocamento": deslocamento, "itens": itens}

    @app.get("/v1/analises/{id_calibracao}", response_model=AnaliseOut,
             responses={404: {"model": ErroOut}}, tags=["análises"],
             summary="Consulta uma análise pelo identificador")
    def obter(id_calibracao: int):
        registro = repo().obter(id_calibracao)
        if registro is None:
            return _erro(404, "NAO_ENCONTRADO", f"Análise {id_calibracao} não encontrada.")
        return _montar(registro)

    @app.get("/v1/modelo-planilha", tags=["análises"],
             summary="Baixa o modelo de planilha de entrada (.xlsx)",
             response_class=Response, responses={200: {"content": {MEDIA_XLSX: {}}}})
    def modelo() -> Response:
        return Response(
            content=gerar_modelo_xlsx(), media_type=MEDIA_XLSX,
            headers={"Content-Disposition": 'attachment; filename="modelo_planilha_analise.xlsx"'})

    return app


app = criar_app()
