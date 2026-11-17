"""Atlas do Desenvolvimento Humano (PNUD, Ipea e FJP): IDHM, Gini e indicadores de renda, via Ipeadata."""
from __future__ import annotations

from sqlalchemy import select

from ..connectors import ipea
from ..log import ctx, get_logger
from ..models import Territory
from ..store import ingestion_run, save_observations

log = get_logger("pipeline.ipea")

# indicador do Atlas -> série do Ipeadata
ADH = {
    "idhm": "ADH_IDHM", "idhm_educacao": "ADH_IDHM_E", "idhm_longevidade": "ADH_IDHM_L", "idhm_renda": "ADH_IDHM_R",
    "gini_censo": "ADH_GINI", "esperanca_vida": "ADH_ESPVIDA", "renda_pc_censo": "ADH_RDPC",
    "pobreza_extrema": "ADH_PIND", "pobreza": "ADH_PMPOB", "renda_10_ricos": "ADH_PREN10RICOS",
}


def rows_for(values: list[ipea.IpeaValue], valid: set[str]) -> list[tuple]:
    """Observações dos territórios da malha atual; sem valor na fonte fica ausente (flag nd)."""
    return [(v.code, v.level, v.period, v.value, None if v.value is not None else "nd") for v in values if v.code in valid]


def run_adh(refresh: bool = False) -> None:
    with ingestion_run("adh", "ipea_adh") as (s, run_):
        valid = set(s.scalars(select(Territory.code)))
        info = {}
        for ind, series in ADH.items():
            rows = rows_for(ipea.fetch_series(series, refresh=refresh), valid)
            info[ind] = dict(serie=series, observacoes=len(rows), anos=sorted({r[2] for r in rows}))
            save_observations(s, run_, ind, rows)
        log.info("Atlas do Desenvolvimento Humano carregado", extra=ctx(indicadores=len(info), observacoes=sum(i["observacoes"] for i in info.values())))
        run_.publication = "Atlas do Desenvolvimento Humano no Brasil (PNUD, Ipea e FJP) — Censos 1991, 2000 e 2010, via Ipeadata"
        run_.params = {**run_.params, "series": info}
