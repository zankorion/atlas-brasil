"""Conectores IBGE: Localidades, Malhas e Agregados (SIDRA) — API servicodados.

Documentação oficial: https://servicodados.ibge.gov.br/api/docs
"""
from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import Iterator

from .base import fetch

LOCALIDADES = "https://servicodados.ibge.gov.br/api/v1/localidades"
MALHAS = "https://servicodados.ibge.gov.br/api/v4/malhas/paises/BR"
AGREGADOS = "https://servicodados.ibge.gov.br/api/v3/agregados"

# Nível SIDRA -> nível do Atlas
LEVELS = {"N1": "BR", "N2": "REGIAO", "N3": "UF", "N6": "MUN"}
# Símbolos convencionais do IBGE para células sem valor numérico.
SYMBOLS = {"...": "nd", "..": "na", "X": "sigilo", "x": "sigilo"}


def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(t.lower().replace("-", " ").replace("'", " ").split())


def parse_value(raw: str | None) -> tuple[float | None, str | None]:
    """Converte o valor textual do SIDRA em (valor, flag).

    '-' é zero absoluto (valor 0.0). '...', '..' e 'X' são ausências com motivo —
    nunca convertidas em zero.
    """
    if raw is None:
        return None, "nd"
    raw = raw.strip()
    if raw == "-":
        return 0.0, None
    if raw in SYMBOLS:
        return None, SYMBOLS[raw]
    try:
        return float(raw), None
    except ValueError:
        return None, "nd"


# ---------------------------------------------------------------- Localidades
def fetch_localidades(refresh: bool = False) -> dict[str, list[dict]]:
    out = {}
    for key, path in {
        "regioes": "regioes",
        "estados": "estados",
        "rgint": "regioes-intermediarias",
        "rgi": "regioes-imediatas",
        "municipios": "municipios",
    }.items():
        raw = fetch(f"{LOCALIDADES}/{path}", namespace="ibge_localidades", cache_key=path, refresh=refresh)
        out[key] = json.loads(raw)
    return out


def territory_rows(loc: dict[str, list[dict]]) -> list[dict]:
    rows = [dict(code="BR", level="BR", name="Brasil", sigla="BR")]
    for r in loc["regioes"]:
        rows.append(dict(code=str(r["id"]), level="REGIAO", name=r["nome"], sigla=r["sigla"], regiao_code=str(r["id"])))
    uf_region = {}
    for u in loc["estados"]:
        uf_region[str(u["id"])] = str(u["regiao"]["id"])
        rows.append(dict(code=str(u["id"]), level="UF", name=u["nome"], sigla=u["sigla"],
                         regiao_code=str(u["regiao"]["id"]), uf_code=str(u["id"])))
    for r in loc["rgint"]:
        uf = str(r["UF"]["id"])
        rows.append(dict(code=str(r["id"]), level="RGINT", name=r["nome"], uf_code=uf,
                         regiao_code=uf_region[uf], rgint_code=str(r["id"])))
    for r in loc["rgi"]:
        rgint = r["regiao-intermediaria"]
        uf = str(rgint["UF"]["id"])
        rows.append(dict(code=str(r["id"]), level="RGI", name=r["nome"], uf_code=uf,
                         regiao_code=uf_region[uf], rgint_code=str(rgint["id"]), rgi_code=str(r["id"])))
    for m in loc["municipios"]:
        code = str(m["id"])
        uf = code[:2]
        rgi = m.get("regiao-imediata") or {}
        rgint = rgi.get("regiao-intermediaria") or {}
        rows.append(dict(code=code, level="MUN", name=m["nome"], uf_code=uf, regiao_code=uf_region.get(uf),
                         rgi_code=str(rgi["id"]) if rgi.get("id") else None,
                         rgint_code=str(rgint["id"]) if rgint.get("id") else None))
    for r in rows:
        r["name_norm"] = normalize(r["name"])
    return rows


# --------------------------------------------------------------------- Malhas
MESH_LEVELS = {
    "REGIAO": "regiao",
    "UF": "UF",
    "RGINT": "regiao-intermediaria",
    "RGI": "regiao-imediata",
    "MUN": "municipio",
}


def fetch_mesh(level: str, refresh: bool = False) -> dict:
    intra = MESH_LEVELS[level]
    url = f"{MALHAS}?formato=application/vnd.geo%2Bjson&qualidade=minima&intrarregiao={intra}"
    raw = fetch(url, namespace="ibge_malhas", cache_key=f"v4_BR_{intra}_minima", suffix=".geojson", refresh=refresh)
    return json.loads(raw)


# ------------------------------------------------------------------ Agregados
@dataclass
class SidraCell:
    code: str
    level: str
    period: str
    value: float | None
    flag: str | None
    categories: dict[str, str]  # id da classificação -> id da categoria


def sidra_periods(table: str, refresh: bool = True) -> list[str]:
    raw = fetch(f"{AGREGADOS}/{table}/periodos", namespace="sidra", cache_key=f"{table}_periodos", refresh=refresh)
    return [p["id"] for p in json.loads(raw)]


def sidra_publication(table: str) -> str:
    """Identificação da publicação: data da última modificação informada pelo IBGE."""
    raw = fetch(f"{AGREGADOS}/{table}/periodos", namespace="sidra", cache_key=f"{table}_periodos")
    mods = [p.get("modificacao") for p in json.loads(raw) if p.get("modificacao")]
    return f"SIDRA {table}; modificação {max(mods)}" if mods else f"SIDRA {table}"


def fetch_sidra(
    table: str,
    variable: str,
    periods: list[str],
    *,
    levels: tuple[str, ...] = ("N1", "N2", "N3", "N6"),
    classification: str | None = None,
    refresh: bool = False,
) -> Iterator[SidraCell]:
    """Consulta uma variável de um agregado para os períodos e níveis dados."""
    loc = "|".join(f"{n}[all]" for n in levels)
    per = "|".join(periods)
    url = f"{AGREGADOS}/{table}/periodos/{per}/variaveis/{variable}?localidades={loc}"
    if classification:
        url += f"&classificacao={classification}"
    key = f"{table}_v{variable}_{'-'.join(periods)}_{'-'.join(levels)}_{classification or 'total'}"
    data = json.loads(fetch(url, namespace="sidra", cache_key=key, refresh=refresh))
    for var in data:
        for res in var["resultados"]:
            cats = {}
            for c in res.get("classificacoes", []):
                cats[str(c["id"])] = next(iter(c["categoria"].keys()))
            for s in res["series"]:
                nivel = s["localidade"]["nivel"]["id"]
                level = LEVELS.get(nivel)
                if not level:
                    continue
                code = "BR" if level == "BR" else str(s["localidade"]["id"])
                for period, raw in s["serie"].items():
                    value, flag = parse_value(raw)
                    yield SidraCell(code, level, period, value, flag, cats)
