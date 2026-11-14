"""Banco Mundial — preços de commodities (Pink Sheet), série mensal do ouro em US$ por onça troy.

O arquivo `CMO-Historical-Data-Monthly.xlsx` muda de endereço a cada publicação; o endereço vigente é lido da
página de mercados de commodities, com um endereço conhecido como reserva.
"""
from __future__ import annotations

import io
import re

import openpyxl

from ..log import ctx, get_logger
from .base import SourceUnavailable, fetch

log = get_logger("connector.worldbank")
PAGE = "https://www.worldbank.org/en/research/commodity-markets"
FALLBACK = "https://thedocs.worldbank.org/en/doc/18675f1d1639c7a34d463f59263ba0a2-0050012025/related/CMO-Historical-Data-Monthly.xlsx"
LINK = re.compile(r'https://thedocs\.worldbank\.org/[^"\']*CMO-Historical-Data-Monthly\.xlsx')


def parse_gold(content: bytes) -> tuple[list[tuple[str, float]], str]:
    """Série (período AAAA-MM, US$/onça troy) e a linha de atualização do arquivo."""
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    if "Monthly Prices" not in wb.sheetnames:
        raise ValueError("planilha 'Monthly Prices' não encontrada no arquivo do Banco Mundial")
    rows = list(wb["Monthly Prices"].iter_rows(values_only=True))
    updated = next((str(r[0]) for r in rows[:8] if isinstance(r[0], str) and r[0].lower().startswith("updated")), "")
    col = unit = None
    for i, r in enumerate(rows[:12]):
        for j, x in enumerate(r):
            if isinstance(x, str) and x.strip().lower() == "gold":
                col, unit = j, str(rows[i + 1][j] or "")
    if col is None:
        raise ValueError("coluna 'Gold' não encontrada no arquivo do Banco Mundial")
    if "troy oz" not in unit.lower():
        raise ValueError(f"unidade inesperada para o ouro: {unit!r} (esperado US$ por onça troy)")
    out = []
    for r in rows:
        m = re.fullmatch(r"(\d{4})M(\d{2})", r[0]) if isinstance(r[0], str) else None
        v = r[col] if m else None
        if m and isinstance(v, (int, float)) and v > 0:  # células vazias ou "…" = mês não publicado: ausente
            out.append((f"{m.group(1)}-{m.group(2)}", float(v)))
    if not out:
        raise ValueError("nenhum preço do ouro reconhecido no arquivo do Banco Mundial")
    return out, updated


def fetch_gold(refresh: bool = True) -> tuple[list[tuple[str, float]], str, str]:
    """(série, linha de atualização, endereço usado)."""
    url = FALLBACK
    try:
        page = fetch(PAGE, namespace="worldbank", cache_key="commodity_markets_page", suffix=".html", refresh=refresh).decode("utf-8", "ignore")
        found = LINK.search(page)
        if found:
            url = found.group(0)
    except SourceUnavailable as e:
        log.warning("página do Banco Mundial indisponível; usando endereço conhecido", extra=ctx(erro=str(e)[:160]))
    serie, updated = parse_gold(fetch(url, namespace="worldbank", cache_key="cmo_monthly", suffix=".xlsx", refresh=refresh))
    return serie, updated, url
