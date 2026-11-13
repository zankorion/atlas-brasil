"""Agregação de indicadores aditivos para níveis não publicados pela fonte (RGI e RGINT)."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from ..log import get_logger
from ..models import Indicator, Observation, Territory, TerritoryChange
from ..store import ingestion_run, save_observations

log = get_logger("aggregate")


def run() -> None:
    with ingestion_run("agregacao", "atlas_derivados") as (s, run_):
        terr = {t.code: (t.rgi_code, t.rgint_code) for t in s.scalars(select(Territory).where(Territory.level == "MUN"))}
        # Município ainda não instalado no período não tem dado e não deve invalidar a soma da região:
        # naquele ano o seu território estava contido no município de origem.
        installed = {ch.code: ch.year for ch in s.scalars(select(TerritoryChange).where(TerritoryChange.kind == "instalacao"))}
        inds = s.scalars(select(Indicator).where(Indicator.additive.is_(True), Indicator.status == "disponivel")).all()
        for ind in inds:
            if "RGI" not in (ind.levels or []) or ind.dataset_id in ("bcb_estban", "bcb_pix"):
                continue  # ESTBAN e Pix já são agregados na própria carga
            sums: dict = defaultdict(float)
            blocked: set = set()
            q = select(Observation.territory_code, Observation.period, Observation.value).where(
                Observation.indicator_id == ind.id, Observation.level == "MUN", Observation.is_current.is_(True))
            for code, period, value in s.execute(q):
                rgi, rgint = terr.get(code, (None, None))
                for lvl, c in (("RGI", rgi), ("RGINT", rgint)):
                    if not c:
                        continue
                    key = (lvl, c, period)
                    if value is None:
                        if int(period[:4]) < installed.get(code, 0):
                            continue
                        blocked.add(key)  # sigilo/ausência em um membro invalida a soma
                    else:
                        sums[key] += value
            rows = [(c, lvl, p, None if (lvl, c, p) in blocked else v, "sigilo" if (lvl, c, p) in blocked else "agg")
                    for (lvl, c, p), v in sums.items()]
            save_observations(s, run_, ind.id, rows)
        run_.publication = "Soma dos municípios (ver metodologia de agregação)"
