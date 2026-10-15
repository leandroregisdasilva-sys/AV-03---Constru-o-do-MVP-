from __future__ import annotations

import os
from pathlib import Path

import pytest

from metrologia_service.calculo import analisar
from metrologia_service.ingestao import ler_planilha

PASTA = os.environ.get("SCHULZ_DADOS_REAIS")
pytestmark = [pytest.mark.real, pytest.mark.skipif(not PASTA, reason="defina SCHULZ_DADOS_REAIS")]


def _arquivos(padrao: str) -> list[Path]:
    return sorted(Path(PASTA).glob(padrao)) if PASTA else []


@pytest.mark.parametrize("arquivo", _arquivos("Registro_MMC*.xlsx") + _arquivos("Cal_1_5896_1*.xlsx"),
                         ids=lambda p: p.name)
def test_planilha_real_e_lida_e_analisada(arquivo):
    pl = ler_planilha(arquivo.read_bytes(), arquivo.name)
    assert pl.pontos, "nenhum ponto de ensaio foi extraído"
    res = analisar(pl.pontos, pl.avisos)
    assert res.parecer.value in ("APROVADO", "REPROVADO")
    assert all(p.situacao.value in ("DENTRO_DA_TOLERANCIA", "FORA_DA_TOLERANCIA") for p in res.pontos)
