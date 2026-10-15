"""Interface web — BFF que conversa com o serviço de metrologia.

O navegador só fala com este serviço; ele repassa o arquivo à API de metrologia
(HTTP/JSON) e renderiza o resultado. Assim a regra de negócio fica em UM lugar
(serviço de metrologia) e a interface pode ser trocada sem tocar nos cálculos.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import __versao__

BASE = Path(__file__).parent
URL_PADRAO = "http://127.0.0.1:8001"

ROTULOS_FORMATO = {
    "calypso_report": "Relatório do Calypso",
    "tabela_de_leituras": "Tabela de leituras",
}



def fmt(valor: Any, minimo: int = 3, maximo: int = 7, sinal: bool = False) -> str:
    """Número em pt-BR: até 7 casas decimais (resolução dos dados), mínimo 3."""
    if valor is None:
        return "—"
    v = float(valor)
    arredondado = f"{abs(v):.{maximo}f}"
    inteiro, _, dec = arredondado.rstrip("0").partition(".")
    texto = f"{inteiro},{dec.ljust(minimo, '0')}"
    if float(arredondado) == 0.0:
        return texto
    if v < 0:
        return f"\u2212{texto}"
    return f"+{texto}" if sinal else texto


def fmt_data(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except ValueError:
        return iso


def fmt_datahora(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.astimezone().strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return iso


def criar_app(metrologia_url: str | None = None,
              transporte: httpx.AsyncBaseTransport | None = None) -> FastAPI:
    """Fábrica da aplicação. ``transporte`` permite testar sem rede (ASGITransport)."""
    app = FastAPI(title="Interface Web – Análise de Calibração (Schulz)", version=__versao__,
                  docs_url=None, redoc_url=None)
    app.state.url = (metrologia_url or os.environ.get("METROLOGIA_URL") or URL_PADRAO).rstrip("/")
    app.state.transporte = transporte
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=str(BASE / "templates"))
    templates.env.filters.update(fmt=fmt, fmt_data=fmt_data, fmt_datahora=fmt_datahora)
    templates.env.globals["rotulo_formato"] = lambda f: ROTULOS_FORMATO.get(f, f)

    def cliente() -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=app.state.url, timeout=30.0, transport=app.state.transporte)

    def pagina(request: Request, nome: str, status: int = 200, **ctx: Any) -> HTMLResponse:
        return templates.TemplateResponse(request, nome, {"versao": __versao__, **ctx},
                                          status_code=status)

    async def servico_ok() -> bool:
        try:
            async with cliente() as c:
                return (await c.get("/health")).status_code == 200
        except httpx.HTTPError:
            return False

    def indisponivel(request: Request) -> HTMLResponse:
        return pagina(request, "erro.html", 503, titulo="Serviço de metrologia indisponível",
                      mensagem="Não foi possível falar com o serviço de metrologia. "
                               "Verifique se ele está em execução e tente novamente.")

    @app.get("/", response_class=HTMLResponse)
    async def inicio(request: Request):
        return pagina(request, "index.html", servico_ok=await servico_ok(), erro=None)

    @app.post("/analisar", response_class=HTMLResponse)
    async def analisar(request: Request, arquivo: UploadFile = File(...)):
        conteudo = await arquivo.read()
        try:
            async with cliente() as c:
                resp = await c.post("/v1/analises", files={
                    "arquivo": (arquivo.filename or "planilha.xlsx", conteudo,
                                arquivo.content_type or "application/octet-stream")})
        except httpx.HTTPError:
            return indisponivel(request)
        if resp.status_code == 201:
            return RedirectResponse(f"/analises/{resp.json()['id_calibracao']}", status_code=303)
        try:
            erro = resp.json().get("erro") or {"codigo": "ERRO", "mensagem": "Falha ao processar.", "detalhes": []}
        except ValueError:
            erro = {"codigo": "ERRO", "mensagem": "Falha ao processar a planilha.", "detalhes": []}
        return pagina(request, "index.html", resp.status_code if resp.status_code >= 400 else 500,
                      servico_ok=True, erro=erro, arquivo_nome=arquivo.filename)

    @app.get("/analises/{id_calibracao}", response_class=HTMLResponse)
    async def resultado(request: Request, id_calibracao: int):
        try:
            async with cliente() as c:
                resp = await c.get(f"/v1/analises/{id_calibracao}")
        except httpx.HTTPError:
            return indisponivel(request)
        if resp.status_code == 404:
            return pagina(request, "erro.html", 404, titulo="Análise não encontrada",
                          mensagem=f"Não existe análise com o número {id_calibracao}.")
        if resp.status_code != 200:
            return indisponivel(request)
        return pagina(request, "resultado.html", analise=resp.json())

    @app.get("/historico", response_class=HTMLResponse)
    async def historico(request: Request):
        try:
            async with cliente() as c:
                resp = await c.get("/v1/analises", params={"limite": 100})
        except httpx.HTTPError:
            return indisponivel(request)
        if resp.status_code != 200:
            return indisponivel(request)
        return pagina(request, "historico.html", lista=resp.json())

    @app.get("/modelo")
    async def modelo():
        try:
            async with cliente() as c:
                resp = await c.get("/v1/modelo-planilha")
        except httpx.HTTPError:
            return JSONResponse({"erro": "serviço de metrologia indisponível"}, status_code=503)
        return Response(resp.content, media_type=resp.headers.get("content-type"),
                        headers={"Content-Disposition": 'attachment; filename="modelo_planilha_analise.xlsx"'})

    @app.get("/saude")
    async def saude():
        ok = await servico_ok()
        return JSONResponse({"status": "ok" if ok else "degradado", "servico": "web",
                             "versao": __versao__, "metrologia": "ok" if ok else "indisponivel"},
                            status_code=200 if ok else 503)

    return app


app = criar_app()
