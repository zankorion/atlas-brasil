"""Cargas do SIDRA/IBGE: PIB dos Municípios, população, domicílios e Censo Agropecuário."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from ..catalog.loader import indicator_specs
from ..config import settings
from ..connectors import ibge
from ..log import ctx, get_logger
from ..models import Territory
from ..stats.core import gini_grouped
from ..store import ingestion_run, save_observations

log = get_logger("sidra")


def _valid_codes(s) -> set[str]:
    return set(s.scalars(select(Territory.code)))


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


LEVEL_CODES = {"BR": "N1", "REGIAO": "N2", "UF": "N3", "MUN": "N6"}


def _origins(ind: dict) -> list[dict]:
    o = ind.get("origem")
    if not o:
        return []
    return [x for x in (o if isinstance(o, list) else [o]) if x.get("tipo") == "sidra"]


def run_catalog(refresh: bool = False, only: str | None = None) -> None:
    """Indicadores declarados no catálogo com origem.tipo = sidra.

    Cada origem informa tabela, variável e, se preciso, a classificação (categorias) — tudo conferido nos
    metadados do agregado. Um indicador pode ter várias origens (ex.: uma tabela até 2021 e outra depois).
    Com `soma: true`, as categorias pedidas são somadas (resultado ausente se alguma parcela for ausente).
    """
    by_dataset = defaultdict(list)
    for i in indicator_specs():
        if _origins(i) and (not only or only in (i["id"], i.get("dataset"))):
            by_dataset[i["dataset"]].append(i)
    for dataset, inds in by_dataset.items():
        tables = sorted({o["tabela"] for i in inds for o in _origins(i)})
        with ingestion_run("sidra", dataset, tabelas=tables) as (s, run):
            valid = _valid_codes(s)
            for ind in inds:
                levels = tuple(LEVEL_CODES[lv] for lv in ind.get("levels", []) if lv in LEVEL_CODES) or ("N1", "N2", "N3", "N6")
                acc: dict = {}
                for o in _origins(ind):
                    periods = [str(p) for p in o["periodos"]] if o.get("periodos") else [
                        p for p in ibge.sidra_periods(o["tabela"]) if len(p) == 4 and int(p) >= settings.start_year]
                    scale = o.get("escala", 1)
                    # tabelas com muitas dimensões cruzadas respondem devagar: `lote: 1` pede um período por vez
                    for chunk in _chunks(periods, int(o.get("lote", 4))):
                        for c in ibge.fetch_sidra(o["tabela"], str(o["variavel"]), chunk, levels=levels,
                                                  classification=o.get("classificacao"), refresh=refresh):
                            if c.code not in valid:
                                continue
                            key = (c.code, c.level, c.period)
                            v = None if c.value is None else c.value * scale
                            if key not in acc:
                                acc[key] = (v, c.flag)
                            elif o.get("soma"):
                                pv, pf = acc[key]
                                acc[key] = (None, pf or c.flag or "nd") if pv is None or v is None else (pv + v, None)
                save_observations(s, run, ind["id"], [(k[0], k[1], k[2], v, f) for k, (v, f) in acc.items()])
            run.publication = "; ".join(ibge.sidra_publication(t) for t in tables)


def run_populacao(refresh: bool = False) -> None:
    """Série composta: censos 2000/2010 (t. 202), censo 2022 (t. 4714) e estimativas (t. 6579)."""
    with ingestion_run("populacao", "sidra_6579") as (s, run):
        valid = _valid_codes(s)
        rows = []
        est_periods = [p for p in ibge.sidra_periods("6579") if int(p) >= settings.start_year]
        for chunk in _chunks(est_periods, 4):
            for c in ibge.fetch_sidra("6579", "9324", chunk, refresh=refresh):
                if c.code in valid:
                    rows.append((c.code, c.level, c.period, c.value, c.flag))
        for c in ibge.fetch_sidra("202", "93", ["2000", "2010"], classification="2[0]|1[0]", refresh=refresh):
            if c.code in valid:
                rows.append((c.code, c.level, c.period, c.value, c.flag))
        for c in ibge.fetch_sidra("4714", "93", ["2022"], refresh=refresh):
            if c.code in valid:
                rows.append((c.code, c.level, c.period, c.value, c.flag))
        # Censos têm precedência caso alguma estimativa coincida com ano censitário.
        dedup = {}
        for r in rows:
            dedup[(r[0], r[2])] = r
        run.publication = "; ".join([ibge.sidra_publication("6579"), "SIDRA 202 (Censos 2000/2010)", "SIDRA 4714 (Censo 2022)"])
        save_observations(s, run, "populacao", dedup.values())


def run_domicilios(refresh: bool = False) -> None:
    """Condição de ocupação dos domicílios nos Censos 2010 e 2022."""
    with ingestion_run("domicilios", "sidra_9930") as (s, run):
        valid = _valid_codes(s)
        out = defaultdict(list)
        # Censo 2010 — tabela 3219: classificação 63 (0 total, 2518 próprio, 1055 alugado)
        m2010 = {"0": "domicilios_total", "2518": "domicilios_proprios", "1055": "domicilios_alugados"}
        for c in ibge.fetch_sidra("3219", "96", ["2010"], refresh=refresh,
                                  classification="68[0]|1[0]|125[0]|63[0,2518,1055]|299[0]"):
            ind = m2010.get(c.categories.get("63"))
            if ind and c.code in valid:
                out[ind].append((c.code, c.level, c.period, c.value, c.flag))
        # Censo 2022 — tabela 9930: classificação 63 (95826 total, 73554 próprio, 1055 alugado)
        m2022 = {"95826": "domicilios_total", "73554": "domicilios_proprios", "1055": "domicilios_alugados"}
        for c in ibge.fetch_sidra("9930", "381", ["2022"], refresh=refresh,
                                  classification="65[95810]|63[95826,73554,1055]|125[2932]"):
            ind = m2022.get(c.categories.get("63"))
            if ind and c.code in valid:
                out[ind].append((c.code, c.level, c.period, c.value, c.flag))
        run.publication = "SIDRA 3219 (Censo 2010); SIDRA 9930 (Censo 2022)"
        for ind, rows in out.items():
            save_observations(s, run, ind, rows)


# Grupos de área total (classificação 220) em ordem crescente; exclui "Produtor sem área".
AREA_GROUPS = ["111543", "111544", "111545", "111546", "111547", "111548", "111549", "111550", "111551",
               "111552", "111553", "111554", "111555", "111556", "111557", "111558", "41139", "40645"]
TOTAL_GROUP = "110085"
# Pontos médios (ha) dos grupos; o último grupo é aberto (10.000 ha e mais) e usa 20.000 ha como referência.
AREA_MIDPOINTS = [0.05, 0.15, 0.35, 0.75, 1.5, 2.5, 3.5, 4.5, 7.5, 15, 35, 75, 150, 350, 750, 1750, 6250, 20000]


def run_censo_agro(refresh: bool = False) -> None:
    """Censo Agropecuário 2017: totais e Gini estimado da área dos estabelecimentos."""
    with ingestion_run("censo_agro", "sidra_6754") as (s, run):
        valid = _valid_codes(s)
        # dados[(code, level)][grupo] = [n_estab, area]
        data: dict = defaultdict(lambda: defaultdict(lambda: [None, None]))
        flags: dict = defaultdict(dict)
        cats = [TOTAL_GROUP] + AREA_GROUPS
        for vi, var in enumerate(("183", "184")):
            for chunk in _chunks(cats, 5):
                cls = f"829[46302]|221[111195]|12517[113601]|220[{','.join(chunk)}]"
                for c in ibge.fetch_sidra("6754", var, ["2017"], classification=cls, refresh=refresh):
                    if c.code not in valid:
                        continue
                    g = c.categories.get("220")
                    data[(c.code, c.level)][g][vi] = c.value
                    if c.flag:
                        flags[(c.code, c.level)][(g, vi)] = c.flag
        estab, area, gini = [], [], []
        n_sigilo = n_imp = 0
        for (code, level), groups in data.items():
            tot = groups.get(TOTAL_GROUP, [None, None])
            f = flags[(code, level)]
            estab.append((code, level, "2017", tot[0], f.get((TOTAL_GROUP, 0))))
            area.append((code, level, "2017", tot[1], f.get((TOTAL_GROUP, 1))))
            ns = [groups[g][0] if g in groups else None for g in AREA_GROUPS]
            ars = [groups[g][1] if g in groups else None for g in AREA_GROUPS]
            if any(v is None for v in ns) or tot[1] is None:
                n_sigilo += 1
                gini.append((code, level, "2017", None, "sigilo"))
                continue
            flag = None
            if any(v is None for v in ars):
                # Imputação residual: a área total é conhecida; o resíduo (total - grupos divulgados) é
                # distribuído entre os grupos sob sigilo proporcionalmente a nº de estabelecimentos x ponto médio.
                known = sum(v for v in ars if v is not None)
                resid = max(tot[1] - known, 0.0)
                w = [n * m if a is None else 0.0 for n, a, m in zip(ns, ars, AREA_MIDPOINTS)]
                sw = sum(w)
                if sw <= 0:
                    ars = [0.0 if a is None else a for a in ars]
                else:
                    ars = [resid * wi / sw if a is None else a for a, wi in zip(ars, w)]
                flag = "imp"
                n_imp += 1
            g = gini_grouped(ns, ars)
            gini.append((code, level, "2017", g, flag if g is not None else "na"))
        run.publication = "SIDRA 6754 (Censo Agropecuário 2017, resultados definitivos)"
        save_observations(s, run, "estab_agro", estab)
        save_observations(s, run, "area_estab_agro", area)
        save_observations(s, run, "gini_fundiario", gini)
        log.info("gini fundiário", extra=ctx(territorios=len(gini), sem_estimativa=n_sigilo, com_imputacao_residual=n_imp))
