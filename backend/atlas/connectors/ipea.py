"""Ipeadata (OData v4): valores de uma série por território.

Usado para o Atlas do Desenvolvimento Humano (PNUD, Ipea e FJP), que o Ipeadata republica por município,
UF e Brasil a partir dos Censos Demográficos de 1991, 2000 e 2010.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .base import fetch

BASE = "http://www.ipeadata.gov.br/api/odata4"
LEVELS = {"Municípios": "MUN", "Estados": "UF", "Brasil": "BR"}


@dataclass(frozen=True)
class IpeaValue:
    code: str
    level: str
    period: str
    value: float | None


def parse_series(body: bytes) -> list[IpeaValue]:
    """Linhas dos níveis que o Atlas usa (município, UF, Brasil). Valor nulo permanece nulo."""
    out = []
    for r in json.loads(body).get("value", []):
        level = LEVELS.get(r.get("NIVNOME"))
        code = str(r.get("TERCODIGO") or "").strip()
        if not level or not code:
            continue
        if level == "BR":
            code = "BR"
        v = r.get("VALVALOR")
        out.append(IpeaValue(code, level, str(r["VALDATA"])[:4], None if v is None else float(v)))
    return out


def fetch_series(code: str, refresh: bool = False) -> list[IpeaValue]:
    return parse_series(fetch(f"{BASE}/ValoresSerie(SERCODIGO='{code}')", namespace="ipeadata", cache_key=code, refresh=refresh))
