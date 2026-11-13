"""Pix por município: totais anuais (soma dos 12 meses) e usuários pagadores em dezembro."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select

from ..connectors import bcb_pix
from ..connectors.base import NotPublished, SourceUnavailable
from ..log import ctx, get_logger
from ..models import Territory
from ..store import ingestion_run, save_observations

log = get_logger("pipeline.pix")

FIRST_FULL_YEAR = 2021  # 2020 só tem novembro e dezembro: não é ano comparável

# indicador -> campos somados (pessoa física + pessoa jurídica)
FLOWS = {
    "pix_valor": ("valor_pago_pf", "valor_pago_pj"),
    "pix_transacoes": ("qtd_pago_pf", "qtd_pago_pj"),
    "pix_valor_recebido": ("valor_recebido_pf", "valor_recebido_pj"),
    "pix_valor_pf": ("valor_pago_pf",),
}
USERS = "pix_usuarios_pf"


def annual(months: list[list[bcb_pix.PixRow]], known: set[str]) -> tuple[dict, dict, dict, dict]:
    """Soma 12 meses por município.

    Um município só tem valor anual se aparecer nos 12 meses com todas as parcelas preenchidas; caso contrário
    o valor fica ausente (nunca soma parcial). Os totais regionais usam a soma de todos os meses publicados de
    cada município (`totais`): as transações de um município presente só em parte do ano ocorreram na região.
    Devolve (fluxos, totais para agregação, usuários de dezembro, resumo).
    """
    assert len(months) == 12
    sums: dict = {k: defaultdict(float) for k in FLOWS}
    seen: dict = {k: defaultdict(int) for k in FLOWS}
    unknown: set[str] = set()
    unknown_value = 0.0
    for rows in months:
        for r in rows:
            if r.ibge not in known:
                unknown.add(r.ibge)
                unknown_value += (r.valor_pago_pf or 0) + (r.valor_pago_pj or 0)
                continue
            for ind, fields in FLOWS.items():
                parts = [getattr(r, f) for f in fields]
                if all(p is not None for p in parts):
                    sums[ind][r.ibge] += sum(parts)
                    seen[ind][r.ibge] += 1
    flows = {ind: {c: (v if seen[ind][c] == 12 else None) for c, v in sums[ind].items()} for ind in FLOWS}
    users = {r.ibge: r.pessoas_pagadoras_pf for r in months[11] if r.ibge in known}
    info = dict(municipios=len(sums["pix_valor"]), incompletos=sum(1 for v in flows["pix_valor"].values() if v is None),
                codigos_desconhecidos=len(unknown), valor_fora_da_malha=round(unknown_value, 2))
    return flows, {ind: dict(v) for ind, v in sums.items()}, users, info


def run(start: int = FIRST_FULL_YEAR, end: int | None = None, refresh: bool = False) -> None:
    start = max(start, FIRST_FULL_YEAR)
    end = end or date.today().year
    with ingestion_run("pix", "bcb_pix", inicio=start, fim=end) as (s, run_):
        terr = {t.code: t for t in s.scalars(select(Territory).where(Territory.level == "MUN"))}
        rows: dict = {k: [] for k in [*FLOWS, USERS]}
        detail = []
        for year in range(start, end + 1):
            months = []
            try:
                for m in range(1, 13):
                    got = bcb_pix.fetch_month(year, m, refresh=refresh)
                    if not got:
                        break
                    months.append(got)
            except (NotPublished, SourceUnavailable) as e:
                log.warning("Pix: ano ignorado", extra=ctx(ano=year, erro=str(e)[:200]))
                continue
            if len(months) < 12:
                # ano incompleto não é publicado no Atlas: a soma parcial pareceria queda
                detail.append(dict(ano=year, meses=len(months), observacao="ano incompleto, não carregado"))
                continue
            flows, totals, users, info = annual(months, set(terr))
            period = str(year)
            for ind, values in flows.items():
                rows[ind] += [(code, "MUN", period, v, None if v is not None else "nd") for code, v in values.items()]
                agg: dict = defaultdict(float)
                for code, v in totals[ind].items():
                    t = terr[code]
                    for lvl, c in (("UF", t.uf_code), ("REGIAO", t.regiao_code), ("BR", "BR"), ("RGINT", t.rgint_code), ("RGI", t.rgi_code)):
                        if c:
                            agg[(lvl, c)] += v
                rows[ind] += [(c, lvl, period, v, "agg") for (lvl, c), v in agg.items()]
            rows[USERS] += [(code, "MUN", period, v, None if v is not None else "nd") for code, v in users.items()]
            detail.append(dict(ano=year, meses=12, **info))
            log.info("Pix por município", extra=ctx(**detail[-1]))
        years = [d["ano"] for d in detail if d["meses"] == 12]
        run_.publication = f"Estatísticas do Pix por município (BCB), {years[0]}–{years[-1]}" if years else "sem dados"
        run_.params = {**run_.params, "anos": detail}
        for ind, r in rows.items():
            save_observations(s, run_, ind, r)
