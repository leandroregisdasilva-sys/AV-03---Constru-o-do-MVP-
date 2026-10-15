"""Contratos (JSON) da API de metrologia."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Situacao = Literal["DENTRO_DA_TOLERANCIA", "FORA_DA_TOLERANCIA"]
Parecer = Literal["APROVADO", "REPROVADO"]


class PontoOut(BaseModel):
    sequencia: int
    ponto: str
    valor_padrao: float = Field(description="Valor padrão de referência (valor nominal), em mm")
    lea_positivo: float = Field(description="|Tol.+|: LEA admitido para erro positivo")
    lea_negativo: float = Field(description="|Tol.−|: LEA admitido para erro negativo")
    leituras: list[float]
    media: float
    desvio_padrao: float = Field(description="Desvio padrão amostral (n−1)")
    erro_sistematico: float = Field(description="média − valor padrão")
    erro_absoluto: float = Field(description="|erro sistemático|")
    lea_aplicado: float = Field(description="LEA do lado em que o erro se encontra")
    limite_minimo: float
    limite_maximo: float
    situacao: Situacao


class ResumoOut(BaseModel):
    total_pontos: int
    dentro_da_tolerancia: int
    fora_da_tolerancia: int
    pontos_fora: list[str]
    maior_desvio_padrao: float
    maior_erro_absoluto: float


class ArquivoOut(BaseModel):
    nome: str
    sha256: str
    formato: str
    aba: str


class MetadadosOut(BaseModel):
    cliente: Optional[str] = None
    tecnico: Optional[str] = None
    codigo_instrumento: Optional[str] = None
    denominacao: Optional[str] = None
    fabricante: Optional[str] = None
    data_calibracao: Optional[str] = None
    temperatura_ambiente: Optional[str] = None
    plano_medicao: Optional[str] = None
    padrao_utilizado: Optional[str] = None


class AnaliseOut(BaseModel):
    id_calibracao: int
    criado_em: str
    parecer: Parecer
    arquivo: ArquivoOut
    metadados: MetadadosOut
    resumo: ResumoOut
    pontos: list[PontoOut]
    avisos: list[str]


class AnaliseResumoOut(BaseModel):
    id_calibracao: int
    criado_em: str
    arquivo_nome: str
    formato: str
    cliente: Optional[str] = None
    tecnico: Optional[str] = None
    codigo_instrumento: Optional[str] = None
    denominacao: Optional[str] = None
    data_calibracao: Optional[str] = None
    total_pontos: int
    pontos_fora: int
    resultado_geral: Parecer


class ListaAnalisesOut(BaseModel):
    total: int
    limite: int
    deslocamento: int
    itens: list[AnaliseResumoOut]


class DetalheErro(BaseModel):
    codigo: str
    mensagem: str
    detalhes: list[str] = []


class ErroOut(BaseModel):
    erro: DetalheErro


class SaudeOut(BaseModel):
    status: Literal["ok"]
    servico: str
    versao: str
