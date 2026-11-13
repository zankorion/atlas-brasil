"""Conectores do Banco Central do Brasil: SGS (séries temporais) e ESTBAN (arquivos mensais).

SGS:    https://dadosabertos.bcb.gov.br (API bcdata.sgs)
ESTBAN: https://www.bcb.gov.br/estatisticas/estatisticabancariamunicipios
"""
from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date

from ..log import ctx, get_logger
from .base import NotPublished, fetch

log = get_logger("bcb")

SGS_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados?formato=json&dataInicial={start}&dataFinal={end}"
ESTBAN_BASE = "https://www.bcb.gov.br/content/estatisticas/estatistica_bancaria_estban/municipio"


# ------------------------------------------------------------------------ SGS
def fetch_sgs(code: int, start: date, end: date | None = None, refresh: bool = True) -> list[tuple[str, float]]:
    """Série mensal do SGS como [(AAAA-MM, valor)].

    A API limita cada consulta a 10 anos; a função percorre janelas sucessivas.
    """
    end = end or date.today()
    out: dict[str, float] = {}
    y = start.year
    win_start = start
    while win_start <= end:
        win_end = min(date(y + 9, 12, 31), end)
        url = SGS_URL.format(code=code, start=win_start.strftime("%d/%m/%Y"), end=win_end.strftime("%d/%m/%Y"))
        closed = win_end < end  # janelas encerradas não mudam: podem vir do cache
        try:
            raw = fetch(url, namespace="bcb_sgs", cache_key=f"sgs{code}_{win_start}_{win_end}", refresh=refresh and not closed)
            rows = json.loads(raw)
        except NotPublished:
            rows = []  # a série ainda não existia nesta janela
        if isinstance(rows, list):
            for r in rows:
                d, m, yy = r["data"].split("/")
                try:
                    out[f"{yy}-{m}"] = float(r["valor"])
                except (TypeError, ValueError):
                    continue
        y += 10
        win_start = date(y, 1, 1)
    return sorted(out.items())


# --------------------------------------------------------------------- ESTBAN
@dataclass
class EstbanMonth:
    period: str  # AAAAMM
    generated: str | None
    # código IBGE do município -> {campo: valor}
    municipalities: dict[str, dict[str, float]] = field(default_factory=dict)
    unmatched_rows: int = 0


def _prefix(col: str) -> str:
    return col.strip().upper()


def _col_groups(header: list[str]) -> dict[str, list[int]]:
    """Mapeia os campos do Atlas para as colunas do arquivo (o leiaute varia no tempo)."""
    groups: dict[str, list[int]] = {k: [] for k in (
        "credito_total", "credito_emprestimos", "credito_financiamentos", "credito_rural",
        "credito_imobiliario", "depositos_vista", "depositos_poupanca", "depositos_prazo")}
    starts = {
        "VERBETE_160": "credito_total",
        "VERBETE_161": "credito_emprestimos",
        "VERBETE_162": "credito_financiamentos",
        "VERBETE_163": "credito_rural",
        "VERBETE_164": "credito_rural",
        "VERBETE_165": "credito_rural",
        "VERBETE_166": "credito_rural",
        "VERBETE_169": "credito_imobiliario",
        "VERBETE_401": "depositos_vista",
        "VERBETE_420": "depositos_poupanca",
        "VERBETE_432": "depositos_prazo",
    }
    for i, col in enumerate(header):
        p = _prefix(col)[:11]
        if p in starts:
            groups[starts[p]].append(i)
    missing = [k for k, v in groups.items() if not v]
    if missing:
        raise ValueError(f"Leiaute ESTBAN inesperado; campos sem coluna: {missing}")
    return groups


def parse_estban(content: bytes, period: str) -> EstbanMonth:
    z = zipfile.ZipFile(io.BytesIO(content))
    text = z.read(z.namelist()[0]).decode("latin-1")
    lines = text.splitlines()
    generated = None
    start = 0
    for i, ln in enumerate(lines[:10]):
        if ln.lower().startswith("data de geracao"):
            generated = ln.split(":", 1)[1].strip()
        if ln.startswith("#DATA_BASE") or ln.startswith("DATA_BASE"):
            start = i
            break
    reader = csv.reader(lines[start:], delimiter=";")
    header = next(reader)
    hmap = {_prefix(c).lstrip("#"): i for i, c in enumerate(header)}
    i_ibge = hmap.get("CODMUN_IBGE")
    i_agen = hmap.get("AGEN_PROCESSADAS")
    if i_ibge is None or i_agen is None:
        raise ValueError("Leiaute ESTBAN inesperado: faltam CODMUN_IBGE ou AGEN_PROCESSADAS")
    groups = _col_groups(header)
    out = EstbanMonth(period=period, generated=generated)

    def num(row, i) -> float:
        try:
            v = row[i].strip()
            return float(v) if v else 0.0
        except (IndexError, ValueError):
            return 0.0

    for row in reader:
        if len(row) <= i_ibge:
            continue
        code = row[i_ibge].strip()
        if not (code.isdigit() and len(code) == 7):
            out.unmatched_rows += 1
            continue
        acc = out.municipalities.setdefault(code, {k: 0.0 for k in groups} | {"agencias": 0.0})
        for k, idxs in groups.items():
            acc[k] += sum(num(row, i) for i in idxs)
        acc["agencias"] += num(row, i_agen)
    return out


def fetch_estban(year: int, month: int = 12, refresh: bool = False) -> EstbanMonth:
    """Baixa e interpreta o ESTBAN por município de um mês. Lança NotPublished se não existir."""
    period = f"{year}{month:02d}"
    last: Exception | None = None
    for name in (f"{period}_ESTBAN.csv.zip", f"{period}_ESTBAN.ZIP", f"{period}_ESTBAN.zip"):
        try:
            raw = fetch(f"{ESTBAN_BASE}/{name}", namespace="bcb_estban", cache_key=period, suffix=".zip", refresh=refresh)
            return parse_estban(raw, period)
        except NotPublished as e:
            last = e
    log.info("ESTBAN não publicado", extra=ctx(periodo=period))
    raise NotPublished(str(last))
