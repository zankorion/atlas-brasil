"""Cargas do Banco Central: ESTBAN (posição de dezembro por município) e séries SGS."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select

from ..catalog.loader import indicator_specs
from ..config import settings
from ..connectors import bcb
from ..connectors.base import NotPublished
from ..log import ctx, get_logger
from ..models import Territory
from ..store import ingestion_run, save_observations

log = get_logger("pipeline.bcb")

ESTBAN_FIELDS = ["credito_total", "credito_emprestimos", "credito_financiamentos", "credito_rural",
                 "credito_imobiliario", "depositos_vista", "depositos_poupanca", "depositos_prazo", "agencias"]


def run_estban(start: int | None = None, end: int | None = None, refresh: bool = False) -> None:
    start = start or 1994
    end = end or date.today().year
    with ingestion_run("estban", "bcb_estban", inicio=start, fim=end, mes=12) as (s, run):
        terr = {t.code: t for t in s.scalars(select(Territory).where(Territory.level == "MUN"))}
        rows = defaultdict(list)
        pubs, unknown = [], 0
        for year in range(start, end + 1):
            try:
                m = bcb.fetch_estban(year, 12, refresh=refresh)
            except NotPublished:
                continue
            pubs.append(f"{m.period} (gerado em {m.generated})")
            period = str(year)
            agg = defaultdict(lambda: defaultdict(float))
            for code, vals in m.municipalities.items():
                t = terr.get(code)
                if t is None:
                    unknown += 1
                    continue
                for k in ESTBAN_FIELDS:
                    rows[k].append((code, "MUN", period, vals[k], None))
                    # Somas por UF, região e Brasil: municípios presentes no arquivo.
                    for lvl, c in (("UF", t.uf_code), ("REGIAO", t.regiao_code), ("BR", "BR"),
                                   ("RGINT", t.rgint_code), ("RGI", t.rgi_code)):
                        if c:
                            agg[(lvl, c)][k] += vals[k]
            for (lvl, c), vals in agg.items():
                for k in ESTBAN_FIELDS:
                    rows[k].append((c, lvl, period, vals[k], "agg"))
            log.info("estban interpretado", extra=ctx(ano=year, municipios=len(m.municipalities), linhas_sem_codigo=m.unmatched_rows))
        if unknown:
            log.warning("códigos de município fora da malha vigente", extra=ctx(ocorrencias=unknown))
        run.publication = "ESTBAN dez/" + (f"{pubs[0][:4]}–{pubs[-1][:4]}" if pubs else "—")
        run.params = {**run.params, "arquivos": pubs}
        for k in ESTBAN_FIELDS:
            save_observations(s, run, k, rows[k])


def run_ouro(refresh: bool = True) -> None:
    """Preço internacional do ouro (Banco Mundial), mensal, desde o início da série em reais."""
    from ..connectors import worldbank

    with ingestion_run("ouro", "bm_commodities") as (s, run):
        serie, updated, url = worldbank.fetch_gold(refresh=refresh)
        rows = [("BR", "BR", p, v, None) for p, v in serie if p >= "1994-07"]
        run.publication = f"Pink Sheet do Banco Mundial ({updated or 'sem data de atualização'}); último mês: {rows[-1][2]}"
        run.params = {"url": url, "meses": len(rows)}
        save_observations(s, run, "ouro_usd", rows)


def run_sgs(refresh: bool = True) -> None:
    specs = [i for i in indicator_specs() if isinstance(i.get("origem"), dict) and i["origem"].get("tipo") == "sgs"]
    start = date(1994, 7, 1)  # marco inicial da série monetária em reais
    with ingestion_run("sgs", "bcb_sgs") as (s, run):
        codes = []
        for ind in specs:
            code = ind["origem"]["codigo"]
            scale = ind["origem"].get("escala", 1)
            serie = bcb.fetch_sgs(code, start, refresh=refresh)
            codes.append(code)
            save_observations(s, run, ind["id"], [("BR", "BR", p, v * scale, None) for p, v in serie])
        run.publication = f"SGS, consulta em {date.today().isoformat()}"
        run.params = {"codigos": codes}
        # Número-índice encadeado do IPCA (dez/1993 = 100) — base do deflacionamento.
        ipca = bcb.fetch_sgs(433, date(1994, 1, 1), refresh=False)
        idx, rows = 100.0, []
        for p, v in ipca:
            idx *= 1 + v / 100
            rows.append(("BR", "BR", p, idx, None))
        save_observations(s, run, "ipca_indice", rows)
    _ = settings
