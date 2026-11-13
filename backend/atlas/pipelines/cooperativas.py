"""Cooperativas de crédito: pontos de atendimento por município e carteira de crédito por UF (SCR.data)."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date

from sqlalchemy import select

from ..connectors import bcb_cadastro as cad
from ..connectors.base import NotPublished, SourceUnavailable
from ..connectors.ibge import normalize
from ..log import ctx, get_logger
from ..models import Territory
from ..store import ingestion_run, save_observations

log = get_logger("pipeline.cooperativas")


# Até 2015 o cadastro lista só uma fração dos postos de cooperativas (801 em dez/2015 contra 4.687 em dez/2016):
# a série começa em 2016 para não confundir ampliação do cadastro com expansão da rede.
FIRST_COMPLETE_YEAR = 2016


def run_postos(start: int = FIRST_COMPLETE_YEAR, end: int | None = None, refresh: bool = False) -> None:
    """Postos de atendimento de cooperativas (posição de dezembro), por município e agregados."""
    start = max(start, FIRST_COMPLETE_YEAR)
    end = end or date.today().year
    with ingestion_run("coop_postos", "bcb_postos", inicio=start, fim=end, mes=12) as (s, run):
        muns = list(s.scalars(select(Territory).where(Territory.level == "MUN")))
        terr = {t.code: t for t in muns}
        ufs = {t.code: t.sigla for t in s.scalars(select(Territory).where(Territory.level == "UF"))}
        by_name = {(t.name_norm, ufs.get(t.uf_code)): t.code for t in muns}
        rows, detail = [], []
        for year in range(start, end + 1):
            try:
                m = cad.fetch_postos(year, 12, refresh=refresh)
            except NotPublished:
                continue
            except (SourceUnavailable, ValueError) as e:
                log.warning("cadastro de postos ignorado", extra=ctx(ano=year, erro=str(e)[:200]))
                continue
            coop = [p for p in m.rows if cad.is_cooperativa(p.segmento)]
            if not coop:
                # arquivos antigos não listam cooperativas: sem dado (ausente), não zero
                detail.append(dict(ano=year, cooperativas=0, observacao="arquivo sem segmento de cooperativas"))
                continue
            count: Counter = Counter()
            unmatched = 0
            for p in coop:
                code = p.ibge if p.ibge in terr else by_name.get((normalize(p.municipio), p.uf))
                if code is None:
                    unmatched += 1
                else:
                    count[code] += 1
            period = str(year)
            agg: dict = defaultdict(float)
            for code, n in count.items():
                t = terr[code]
                rows.append((code, "MUN", period, float(n), None))
                for lvl, c in (("UF", t.uf_code), ("REGIAO", t.regiao_code), ("BR", "BR"), ("RGINT", t.rgint_code), ("RGI", t.rgi_code)):
                    if c:
                        agg[(lvl, c)] += n
            rows += [(c, lvl, period, v, "agg") for (lvl, c), v in agg.items()]
            detail.append(dict(ano=year, posicao=m.position, cooperativas=len(coop), municipios=len(count),
                               sem_municipio=unmatched, por="codigo_ibge" if m.has_ibge_code else "nome_e_uf"))
            log.info("postos de cooperativas", extra=ctx(**detail[-1]))
        years = [d["ano"] for d in detail if d["cooperativas"]]
        run.publication = f"Cadastro de postos de atendimento do BCB, dez/{years[0]}–{years[-1]}" if years else "sem dados"
        run.params = {**run.params, "arquivos": detail}
        save_observations(s, run, "cooperativas_credito", rows)


TCB_FIELDS = {"cooperativas": "credito_scr_coop", "bancário": "credito_scr_bancos"}


def run_scr(start: int = 2012, end: int | None = None, refresh: bool = False) -> None:
    """Carteira ativa de dezembro por UF do tomador: total, bancos e cooperativas (SCR.data)."""
    end = end or date.today().year
    with ingestion_run("scr", "bcb_scr", inicio=start, fim=end, mes=12) as (s, run):
        ufs = {t.sigla: t for t in s.scalars(select(Territory).where(Territory.level == "UF"))}
        rows: dict = defaultdict(list)
        done, tipos, unknown, sem_tipo = [], set(), Counter(), []
        for year in range(start, end + 1):
            try:
                d = cad.fetch_scr_december(year, refresh=refresh)
            except NotPublished:
                continue
            period = str(year)
            agg: dict = defaultdict(lambda: defaultdict(float))
            # Há arquivos em que a fonte publica o tipo de instituição vazio ("-") em todas as linhas: o total vale,
            # mas a abertura por tipo fica AUSENTE nesse ano — não zero.
            typed = any(r["tcb"].lower() in TCB_FIELDS for r in d["data"])
            if not typed:
                sem_tipo.append(year)
            for r in d["data"]:
                tipos.add(r["tcb"])
                t = ufs.get(r["uf"])
                if t is None or r["valor"] is None:
                    unknown[r["uf"]] += 1
                    continue
                fields = ["credito_scr"] + ([TCB_FIELDS[r["tcb"].lower()]] if r["tcb"].lower() in TCB_FIELDS else [])
                for f in fields:
                    for key in (("UF", t.code), ("REGIAO", t.regiao_code), ("BR", "BR")):
                        agg[key][f] += r["valor"]
            for (lvl, code), vals in agg.items():
                rows["credito_scr"].append((code, lvl, period, vals["credito_scr"], None if lvl == "UF" else "agg"))
                for f in ("credito_scr_coop", "credito_scr_bancos"):
                    if typed:  # tipo sem nenhuma linha na UF = carteira zero naquele recorte (o total da UF existe)
                        rows[f].append((code, lvl, period, vals.get(f, 0.0), None if lvl == "UF" else "agg"))
                    else:
                        rows[f].append((code, lvl, period, None, "nd"))
            done.append(year)
        if sem_tipo:
            log.warning("SCR.data sem tipo de instituição; abertura ausente", extra=ctx(anos=sem_tipo))
        if unknown:
            log.warning("UF não reconhecida no SCR.data", extra=ctx(ocorrencias=dict(unknown)))
        run.publication = f"SCR.data, dez/{done[0]}–{done[-1]}" if done else "sem dados"
        run.params = {**run.params, "anos": done, "tipos_de_instituicao": sorted(tipos),
                      "anos_sem_tipo_de_instituicao": sem_tipo}
        for f, r in rows.items():
            save_observations(s, run, f, r)
