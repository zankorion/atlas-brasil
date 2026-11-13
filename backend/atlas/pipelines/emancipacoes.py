"""Alterações da malha municipal desde 1991: municípios instalados e municípios de origem.

Método (ver metodologia "Divisão territorial"):

1. **Quando** — presença de cada município nas publicações de população do IBGE, que usam a malha vigente em
   cada data: Censo 1991, Contagem 1996, Censo 2000 e estimativas anuais de 2001 em diante. O primeiro ano em que
   o município aparece delimita a instalação. Como prefeitos tomam posse em 1º de janeiro do ano seguinte ao da
   eleição municipal, um município ausente em 1996 e presente em 2000 foi instalado em 1997.
2. **De onde** — municípios de origem extraídos do texto "Formação administrativa" da Biblioteca do IBGE
   ("... desmembrado de X"), por leitura automática. Quando o texto não existe ou não é reconhecido, a origem fica
   não identificada. Uma lista conferida manualmente (instalações desde 2005) tem precedência.
"""
from __future__ import annotations

import json
import re

from sqlalchemy import select

from ..connectors import ibge
from ..connectors.base import NotPublished, SourceUnavailable, fetch
from ..log import ctx, get_logger
from ..models import Territory, TerritoryChange
from ..store import ingestion_run

log = get_logger("emancipacoes")

# Instalações desde 2005 conferidas manualmente: (ano, (município, UF), [(origem, UF), ...]).
CURATED = [
    (2005, ("Aroeiras do Itaim", "PI"), [("Picos", "PI")]),
    (2005, ("Figueirão", "MS"), [("Camapuã", "MS"), ("Costa Rica", "MS")]),
    (2005, ("Ipiranga do Norte", "MT"), [("Tapurah", "MT")]),
    (2005, ("Itanhangá", "MT"), [("Tapurah", "MT")]),
    (2009, ("Nazária", "PI"), [("Teresina", "PI")]),
    (2013, ("Pescaria Brava", "SC"), [("Laguna", "SC")]),
    (2013, ("Balneário Rincão", "SC"), [("Içara", "SC")]),
    (2013, ("Mojuí dos Campos", "PA"), [("Santarém", "PA")]),
    (2013, ("Pinto Bandeira", "RS"), [("Bento Gonçalves", "RS")]),
    (2013, ("Paraíso das Águas", "MS"), [("Água Clara", "MS"), ("Costa Rica", "MS"), ("Chapadão do Sul", "MS")]),
    (2025, ("Boa Esperança do Norte", "MT"), [("Sorriso", "MT"), ("Nova Ubiratã", "MT")]),
]
# Primeiro ano com população -> ano de instalação, para as publicações que não são anuais.
WAVE = {"1996": 1993, "2000": 1997}
BIBLIOTECA = "https://servicodados.ibge.gov.br/api/v1/biblioteca?aspas=3&codmun={cod}"
ORIGIN_RE = re.compile(r"desmembrad[oa]s?\s+d[oae]s?\s+(?:munic[ií]pios?\s+(?:de\s+|do\s+|da\s+)?)?([^.;\n]{3,160})", re.I)


def _present(table: str, variable: str, periods: list[str], classification: str | None = None) -> dict[str, set[str]]:
    """período -> códigos de municípios com população publicada (valor numérico)."""
    out: dict[str, set[str]] = {p: set() for p in periods}
    for i in range(0, len(periods), 4):
        for c in ibge.fetch_sidra(table, variable, periods[i:i + 4], levels=("N6",), classification=classification):
            if c.value is not None and c.value > 0:
                out[c.period].add(c.code)
    return out


def _totals(table: str) -> str:
    """Classificação com a categoria 'Total' de cada dimensão do agregado."""
    meta = json.loads(fetch(f"{ibge.AGREGADOS}/{table}/metadados", namespace="sidra", cache_key=f"{table}_metadados"))
    parts = []
    for c in meta["classificacoes"]:
        total = next((k["id"] for k in c["categorias"] if str(k["nome"]).strip().lower() == "total"), c["categorias"][0]["id"])
        parts.append(f"{c['id']}[{total}]")
    return "|".join(parts)


def parse_origins(text: str) -> list[str]:
    """Nomes de municípios de origem citados após 'desmembrado de' no texto de formação administrativa."""
    names: list[str] = []
    for m in ORIGIN_RE.finditer(text or ""):
        chunk = re.split(r"\b(?:[Ss]ede|[Cc]onstitu[ií]do|[Ii]nstalad[oa]|pela\s+[Ll]ei|pelo\s+[Dd]ecreto|[Ee]m\s+divis)", m.group(1))[0]
        for part in re.split(r",|\s+e\s+", chunk):
            n = re.sub(r"^(?:o\s+distrito\s+de\s+.*|os?\s+|as?\s+|d[oae]s?\s+|munic[ií]pios?\s+(?:de\s+)?)", "", part.strip(), flags=re.I).strip(" .:-")
            n = re.split(r"\s+o\s+distrito" + chr(92) + "b", n)[0].strip()
            if 2 < len(n) < 60 and n not in names:
                names.append(n)
    return names


def run(refresh: bool = False) -> None:
    with ingestion_run("emancipacoes", "ibge_localidades") as (s, run_):
        muns = list(s.scalars(select(Territory).where(Territory.level == "MUN")))
        ufs = {t.code: t.sigla for t in s.scalars(select(Territory).where(Territory.level == "UF"))}
        by_name = {(t.name_norm, ufs.get(t.uf_code)): t.code for t in muns}
        name_of = {t.code: t.name for t in muns}

        # 1) presença por publicação
        presence: dict[str, set[str]] = {}
        presence.update(_present("202", "93", ["1991", "2000"], "2[0]|1[0]"))
        presence.update(_present("475", "93", ["1996"], _totals("475")))
        est = [p for p in ibge.sidra_periods("6579")]
        presence.update(_present("6579", "9324", est))
        years = sorted(presence)
        if len(presence["1991"]) < 4000 or len(presence["1996"]) < 4500:
            raise RuntimeError(f"Presença censitária implausível (1991: {len(presence['1991'])}; 1996: {len(presence['1996'])}).")

        first: dict[str, str] = {}
        for t in muns:
            f = next((y for y in years if t.code in presence[y]), None)
            if f:
                first[t.code] = f
        curated = {by_name.get((ibge.normalize(n), uf)): (year, [by_name.get((ibge.normalize(pn), puf)) for pn, puf in parents])
                   for year, (n, uf), parents in CURATED}

        s.query(TerritoryChange).delete()
        ceded: dict = {}
        stats = dict(instalados=0, origem_identificada=0, origem_nao_identificada=0, sem_texto=0)
        for t in sorted(muns, key=lambda t: t.code):
            f = first.get(t.code)
            if t.code in curated:
                year, parents = curated[t.code]
                parents = [p for p in parents if p]
                how = "Ano e origem conferidos manualmente."
            elif f and f > "1991":
                year = WAVE.get(f, int(f))
                parents, how = [], ""
                try:
                    raw = fetch(BIBLIOTECA.format(cod=t.code[:6]), namespace="ibge_biblioteca", cache_key=t.code, refresh=refresh)
                    rec = next(iter(json.loads(raw).values()), {}) if raw.strip() not in (b"", b"[]", b"{}") else {}
                    text = rec.get("FORMACAO_ADMINISTRATIVA") or ""
                except (NotPublished, SourceUnavailable, ValueError, AttributeError):
                    text = ""
                if not text:
                    stats["sem_texto"] += 1
                for n in parse_origins(text):
                    code = by_name.get((ibge.normalize(n), ufs.get(t.uf_code)))
                    if code and code != t.code and code not in parents and first.get(code, "9999") < f:
                        parents.append(code)
                how = (f"Ano inferido: primeira publicação de população do IBGE com o município é a de {f}. "
                       + ("Origem extraída automaticamente do texto de formação administrativa do IBGE."
                          if parents else "Município de origem não identificado automaticamente."))
            else:
                continue
            stats["instalados"] += 1
            stats["origem_identificada" if parents else "origem_nao_identificada"] += 1
            origem = f", desmembrado de {', '.join(name_of[p] for p in parents)}" if parents else ""
            s.add(TerritoryChange(code=t.code, kind="instalacao", year=year, related_codes=parents,
                                  note=f"Município instalado em {year}{origem}. {how}"))
            for p in parents:
                ceded.setdefault((p, year), []).append((t.code, t.name))
        for (p, year), created in ceded.items():
            s.add(TerritoryChange(code=p, kind="cessao_de_area", year=year, related_codes=[c for c, _ in created],
                                  note=f"Cedeu área para a criação de {', '.join(n for _, n in created)} ({year})."))
        by_year: dict[int, int] = {}
        for ch in s.new:
            if isinstance(ch, TerritoryChange) and ch.kind == "instalacao":
                by_year[ch.year] = by_year.get(ch.year, 0) + 1
        run_.rows_new = stats["instalados"] + len(ceded)
        run_.publication = "IBGE: SIDRA 202, 475 e 6579 (presença por publicação) e Biblioteca (formação administrativa)"
        run_.params = {**stats, "cedentes": len(ceded), "por_ano": {str(k): v for k, v in sorted(by_year.items())}}
        log.info("alterações territoriais", extra=ctx(**run_.params))
