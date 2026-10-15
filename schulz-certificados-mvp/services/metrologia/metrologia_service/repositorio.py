"""Persistência transacional (SQLite) das análises.

Modelo derivado do Dicionário de Dados (CALIBRACAO / RESULTADO_MEDICAO).
Cada análise é gravada em UMA transação: ou o cabeçalho e todos os pontos são
persistidos, ou nada é (atomicidade). Os registros nunca são alterados nem
apagados pela API — rastreabilidade exigida em auditoria (ISO/IEC 17025).

Na nuvem este módulo é substituído pelo acesso ao DynamoDB; o restante
do serviço não muda, pois só conversa com a classe ``Repositorio``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .calculo import ResultadoAnalise

ESQUEMA = """
CREATE TABLE IF NOT EXISTS calibracao (
    id_calibracao      INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em          TEXT    NOT NULL,
    arquivo_nome       TEXT    NOT NULL,
    arquivo_sha256     TEXT    NOT NULL,
    formato            TEXT    NOT NULL,
    aba                TEXT    NOT NULL,
    cliente            TEXT,
    tecnico            TEXT,
    codigo_instrumento TEXT,
    denominacao        TEXT,
    fabricante         TEXT,
    data_calibracao    TEXT,
    temperatura_ambiente TEXT,
    plano_medicao      TEXT,
    padrao_utilizado   TEXT,
    total_pontos       INTEGER NOT NULL,
    pontos_fora        INTEGER NOT NULL,
    resultado_geral    TEXT    NOT NULL CHECK (resultado_geral IN ('APROVADO','REPROVADO')),
    avisos_json        TEXT    NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS resultado_medicao (
    id_resultado     INTEGER PRIMARY KEY AUTOINCREMENT,
    id_calibracao    INTEGER NOT NULL REFERENCES calibracao(id_calibracao) ON DELETE RESTRICT,
    sequencia        INTEGER NOT NULL,
    ponto            TEXT    NOT NULL,
    valor_padrao     REAL    NOT NULL,
    lea_positivo     REAL    NOT NULL,
    lea_negativo     REAL    NOT NULL,
    leituras_json    TEXT    NOT NULL,
    media            REAL    NOT NULL,
    desvio_padrao    REAL    NOT NULL,
    erro_sistematico REAL    NOT NULL,
    erro_absoluto    REAL    NOT NULL,
    lea_aplicado     REAL    NOT NULL,
    limite_minimo    REAL    NOT NULL,
    limite_maximo    REAL    NOT NULL,
    situacao         TEXT    NOT NULL CHECK (situacao IN ('DENTRO_DA_TOLERANCIA','FORA_DA_TOLERANCIA')),
    UNIQUE (id_calibracao, sequencia)
);
CREATE INDEX IF NOT EXISTS ix_calibracao_criado ON calibracao (criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_resultado_calibracao ON resultado_medicao (id_calibracao);
"""

CAMPOS_META = ("cliente", "tecnico", "codigo_instrumento", "denominacao", "fabricante",
               "data_calibracao", "temperatura_ambiente", "plano_medicao", "padrao_utilizado")


def caminho_padrao() -> str:
    return os.environ.get("METROLOGIA_DB", str(Path("data") / "metrologia.db"))


class Repositorio:
    def __init__(self, caminho: str | None = None):
        self.caminho = caminho or caminho_padrao()
        if self.caminho != ":memory:":
            Path(self.caminho).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._mem: sqlite3.Connection | None = None
        with self._conexao() as con:
            con.executescript(ESQUEMA)

    @contextmanager
    def _conexao(self) -> Iterator[sqlite3.Connection]:
        if self.caminho == ":memory:":
            if self._mem is None:
                self._mem = sqlite3.connect(":memory:", check_same_thread=False)
                self._mem.row_factory = sqlite3.Row
                self._mem.execute("PRAGMA foreign_keys = ON")
            con = self._mem
            try:
                yield con
                con.commit()
            except Exception:
                con.rollback()
                raise
            return
        con = sqlite3.connect(self.caminho, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        try:
            yield con
            con.commit()          
        except Exception:
            con.rollback()        
            raise
        finally:
            con.close()

   
    def salvar(self, *, arquivo_nome: str, arquivo_sha256: str, formato: str, aba: str,
               metadados: dict[str, str | None], analise: ResultadoAnalise) -> int:
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._conexao() as con:
            cur = con.execute(
                f"""INSERT INTO calibracao (criado_em, arquivo_nome, arquivo_sha256, formato, aba,
                    {", ".join(CAMPOS_META)}, total_pontos, pontos_fora, resultado_geral, avisos_json)
                    VALUES (?,?,?,?,?,{",".join("?" * len(CAMPOS_META))},?,?,?,?)""",
                (agora, arquivo_nome, arquivo_sha256, formato, aba,
                 *(metadados.get(c) for c in CAMPOS_META),
                 analise.total, len(analise.fora), analise.parecer.value,
                 json.dumps(list(analise.avisos), ensure_ascii=False)),
            )
            id_cal = int(cur.lastrowid)
            con.executemany(
                """INSERT INTO resultado_medicao (id_calibracao, sequencia, ponto, valor_padrao,
                    lea_positivo, lea_negativo, leituras_json, media, desvio_padrao,
                    erro_sistematico, erro_absoluto, lea_aplicado, limite_minimo, limite_maximo, situacao)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(id_cal, p.sequencia, p.ponto, p.valor_padrao, p.lea_positivo, p.lea_negativo,
                  json.dumps(list(p.leituras)), p.media, p.desvio_padrao, p.erro_sistematico,
                  p.erro_absoluto, p.lea_aplicado, p.limite_minimo, p.limite_maximo,
                  p.situacao.value) for p in analise.pontos],
            )
            return id_cal

 
    def obter(self, id_calibracao: int) -> dict[str, Any] | None:
        with self._conexao() as con:
            cab = con.execute("SELECT * FROM calibracao WHERE id_calibracao = ?",
                              (id_calibracao,)).fetchone()
            if cab is None:
                return None
            pontos = con.execute(
                "SELECT * FROM resultado_medicao WHERE id_calibracao = ? ORDER BY sequencia",
                (id_calibracao,)).fetchall()
        dados = dict(cab)
        dados["avisos"] = json.loads(dados.pop("avisos_json"))
        dados["pontos"] = []
        for p in pontos:
            d = dict(p)
            d["leituras"] = json.loads(d.pop("leituras_json"))
            dados["pontos"].append(d)
        return dados

    def listar(self, limite: int = 50, deslocamento: int = 0) -> tuple[int, list[dict[str, Any]]]:
        with self._conexao() as con:
            total = con.execute("SELECT COUNT(*) FROM calibracao").fetchone()[0]
            linhas = con.execute(
                "SELECT * FROM calibracao ORDER BY id_calibracao DESC LIMIT ? OFFSET ?",
                (limite, deslocamento)).fetchall()
        itens = []
        for l in linhas:
            d = dict(l)
            d.pop("avisos_json", None)
            itens.append(d)
        return total, itens
