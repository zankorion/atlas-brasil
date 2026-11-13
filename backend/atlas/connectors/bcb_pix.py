"""Estatísticas do Pix por município (Banco Central, dados abertos — serviço Olinda `Pix_DadosAbertos`).

O recurso `TransacoesPixPorMunicipio(DataBase)` devolve todos os meses a partir de `DataBase`; cada mês é
lido separadamente (filtro `AnoMes`) e guardado no cache bruto.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .base import fetch

BASE = "https://olinda.bcb.gov.br/olinda/servico/Pix_DadosAbertos/versao/v1/odata/TransacoesPixPorMunicipio(DataBase=@DataBase)"
FIRST_MONTH = "202011"  # o Pix entrou em operação plena em 16/11/2020
FIELDS = ("Municipio_Ibge", "VL_PagadorPF", "QT_PagadorPF", "VL_PagadorPJ", "QT_PagadorPJ",
          "VL_RecebedorPF", "VL_RecebedorPJ", "QT_PES_PagadorPF")


@dataclass
class PixRow:
    ibge: str
    valor_pago_pf: float | None
    valor_pago_pj: float | None
    qtd_pago_pf: float | None
    qtd_pago_pj: float | None
    valor_recebido_pf: float | None
    valor_recebido_pj: float | None
    pessoas_pagadoras_pf: float | None


def _num(v) -> float | None:
    """Número da fonte; nulo permanece nulo (ausente), nunca vira zero."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_month(content: bytes) -> list[PixRow]:
    rows = json.loads(content).get("value", [])
    out = []
    for r in rows:
        code = r.get("Municipio_Ibge")
        if code is None:
            continue
        out.append(PixRow(
            ibge=str(int(code)), valor_pago_pf=_num(r.get("VL_PagadorPF")), valor_pago_pj=_num(r.get("VL_PagadorPJ")),
            qtd_pago_pf=_num(r.get("QT_PagadorPF")), qtd_pago_pj=_num(r.get("QT_PagadorPJ")),
            valor_recebido_pf=_num(r.get("VL_RecebedorPF")), valor_recebido_pj=_num(r.get("VL_RecebedorPJ")),
            pessoas_pagadoras_pf=_num(r.get("QT_PES_PagadorPF"))))
    return out


def fetch_month(year: int, month: int, refresh: bool = False) -> list[PixRow]:
    """Linhas de um mês; lista vazia quando o mês ainda não foi publicado."""
    ym = f"{year}{month:02d}"
    url = (f"{BASE}?@DataBase='{FIRST_MONTH}'&$filter=AnoMes%20eq%20{ym}&$select={','.join(FIELDS)}&$format=json")
    return parse_month(fetch(url, namespace="bcb_pix", cache_key=f"pix_municipio_{ym}", refresh=refresh))
