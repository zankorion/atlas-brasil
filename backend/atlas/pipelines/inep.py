"""Educação básica (INEP): IDEB, Censo Escolar e taxas de rendimento e de distorção idade-série."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select

from ..connectors import inep
from ..connectors.base import NotPublished, SourceUnavailable
from ..log import ctx, get_logger
from ..models import Territory
from ..store import ingestion_run, save_observations

log = get_logger("pipeline.inep")

IDEB = {"anos_iniciais": "ideb_anos_iniciais", "anos_finais": "ideb_anos_finais", "ensino_medio": "ideb_ensino_medio"}
# campo do conector -> indicador do Atlas
CENSUS = {"escolas": "esc_escolas", "matriculas": "esc_matriculas", "mat_creche": "esc_mat_creche", "mat_pre": "esc_mat_pre",
          "mat_fund_ai": "esc_mat_fund_ai", "mat_fund_af": "esc_mat_fund_af", "mat_medio": "esc_mat_medio", "mat_eja": "esc_mat_eja",
          "mat_prof": "esc_mat_prof", "turmas": "esc_turmas", "mat_publica": "esc_mat_publica", "mat_municipal": "esc_mat_municipal",
          "mat_privada": "esc_mat_privada"}
RATES = {"aprovacao_fund": "edu_aprovacao_fund", "reprovacao_fund": "edu_reprovacao_fund", "abandono_fund": "edu_abandono_fund",
         "aprovacao_medio": "edu_aprovacao_medio", "reprovacao_medio": "edu_reprovacao_medio", "abandono_medio": "edu_abandono_medio"}
TDI = {"distorcao_fund": "edu_distorcao_fund", "distorcao_medio": "edu_distorcao_medio"}


def run_ideb(refresh: bool = False) -> None:
    """IDEB da rede pública por município: o arquivo da última edição traz a série completa (bienal, desde 2005)."""
    with ingestion_run("ideb", "inep_ideb", edicao=inep.IDEB_EDITION) as (s, run_):
        valid = set(s.scalars(select(Territory.code).where(Territory.level == "MUN")))
        info = {}
        for stage, ind in IDEB.items():
            data = inep.fetch_ideb(stage, refresh=refresh)
            rows = [(code, "MUN", year, v, None if v is not None else "nd") for (code, year), v in data.items() if code in valid]
            info[stage] = dict(observacoes=len(rows), com_valor=sum(1 for r in rows if r[3] is not None))
            save_observations(s, run_, ind, rows)
        log.info("IDEB carregado", extra=ctx(**info))
        run_.publication = f"IDEB {inep.IDEB_EDITION} — resultados por município, rede pública"
        run_.params = {**run_.params, **info}


def census_rows(df, terr: dict[str, Territory], period: str) -> tuple[dict[str, list], int]:
    """Linhas por indicador, do município e dos níveis superiores (soma exata: toda escola tem município).

    Município sem nenhuma escola em atividade no ano não gera observação. Onde há escolas, uma etapa sem
    matrículas é zero de verdade (o Censo Escolar é um levantamento completo), não ausência.
    """
    out: dict[str, list] = {ind: [] for ind in CENSUS.values()}
    unknown = 0
    agg: dict = {f: defaultdict(float) for f in CENSUS}
    for rec in df.iter_rows(named=True):
        t = terr.get(rec["code"])
        if t is None:
            unknown += 1
            continue
        for field, ind in CENSUS.items():
            v = rec[field]
            out[ind].append((t.code, "MUN", period, v, None if v is not None else "nd"))
            if v is None:
                continue
            for lvl, c in (("UF", t.uf_code), ("REGIAO", t.regiao_code), ("BR", "BR"), ("RGINT", t.rgint_code), ("RGI", t.rgi_code)):
                if c:
                    agg[field][(lvl, c)] += v
    for field, ind in CENSUS.items():
        out[ind] += [(c, lvl, period, v, "agg") for (lvl, c), v in agg[field].items()]
    return out, unknown


def run_censo_escolar(start: int = inep.CENSUS_FIRST, end: int | None = None, refresh: bool = False) -> None:
    start = max(start, inep.CENSUS_FIRST)
    end = end or date.today().year - 1
    with ingestion_run("censo_escolar", "inep_censo_escolar", inicio=start, fim=end) as (s, run_):
        terr = {t.code: t for t in s.scalars(select(Territory).where(Territory.level == "MUN"))}
        rows: dict[str, list] = {ind: [] for ind in CENSUS.values()}
        detail = []
        for year in range(start, end + 1):
            try:
                df = inep.fetch_census(year, refresh=refresh)
            except (NotPublished, SourceUnavailable) as e:
                log.warning("Censo Escolar: ano ignorado", extra=ctx(ano=year, erro=str(e)[:200]))
                continue
            got, unknown = census_rows(df, terr, str(year))
            for ind, r in got.items():
                rows[ind] += r
            total = df["matriculas"].sum()
            detail.append(dict(ano=year, municipios=df.height, fora_da_malha=unknown, escolas=int(df["escolas"].sum()),
                               matriculas=int(total) if total is not None else None))
            log.info("Censo Escolar por município", extra=ctx(**detail[-1]))
        years = [d["ano"] for d in detail]
        run_.publication = f"Censo Escolar (microdados da educação básica), {years[0]}–{years[-1]}" if years else "sem dados"
        run_.params = {**run_.params, "anos": detail}
        for ind, r in rows.items():
            save_observations(s, run_, ind, r)


def _run_rates(pipeline: str, dataset: str, mapping: dict[str, str], fetcher, first: int, start: int | None, end: int | None,
               refresh: bool, label: str) -> None:
    start = max(start or first, first)
    end = end or date.today().year - 1
    with ingestion_run(pipeline, dataset, inicio=start, fim=end) as (s, run_):
        valid = set(s.scalars(select(Territory.code).where(Territory.level == "MUN")))
        rows: dict[str, list] = {ind: [] for ind in mapping.values()}
        detail = []
        for year in range(start, end + 1):
            try:
                data = fetcher(year, refresh=refresh)
            except (NotPublished, SourceUnavailable, inep.LayoutChanged) as e:
                log.warning(f"{label}: ano ignorado", extra=ctx(ano=year, erro=str(e)[:200]))
                detail.append(dict(ano=year, observacao=f"não carregado: {str(e)[:120]}"))
                continue
            for code, rec in data.items():
                if code in valid:
                    for field, ind in mapping.items():
                        v = rec[field]
                        rows[ind].append((code, "MUN", str(year), v, None if v is not None else "nd"))
            detail.append(dict(ano=year, municipios=len(data)))
            log.info(f"{label} por município", extra=ctx(**detail[-1]))
        years = [d["ano"] for d in detail if "municipios" in d]
        run_.publication = f"{label} por município (INEP), {years[0]}–{years[-1]}" if years else "sem dados"
        run_.params = {**run_.params, "anos": detail}
        for ind, r in rows.items():
            save_observations(s, run_, ind, r)


def run_rendimento(start: int | None = None, end: int | None = None, refresh: bool = False) -> None:
    _run_rates("rendimento", "inep_indicadores", RATES, inep.fetch_rates, inep.RATES_FIRST, start, end, refresh, "Taxas de rendimento")


def run_distorcao(start: int | None = None, end: int | None = None, refresh: bool = False) -> None:
    _run_rates("distorcao", "inep_indicadores", TDI, inep.fetch_tdi, inep.TDI_FIRST, start, end, refresh, "Distorção idade-série")
