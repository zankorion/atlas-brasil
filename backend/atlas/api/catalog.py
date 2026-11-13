"""Rotas de catálogo: indicadores, fontes, metodologias, territórios, malhas e cargas."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import case, func, or_, select

from ..catalog.loader import read_catalog
from ..config import settings
from ..connectors.ibge import normalize
from ..data import LEVEL_NAMES, LEVELS
from ..models import Dataset, Indicator, IngestionRun, Methodology, Observation, Source, Territory, TerritoryChange, Unit
from .deps import Ctx, ctx

router = APIRouter(prefix="/api")


def _ind(i: Indicator, u: Unit, d: Dataset | None, src: Source | None) -> dict:
    return dict(id=i.id, name=i.name, short_name=i.short_name or i.name, description=i.description, dimension=i.dimension,
                unit=u.label, percent=u.percent, nature=i.nature, value_kind=i.value_kind, stock_flow=i.stock_flow,
                frequency=i.frequency, levels=i.levels, status=i.status, formula=i.formula, limitations=i.limitations,
                breaks=i.breaks, decimals=i.decimals, methodology_id=i.methodology_id,
                dataset=d.name if d else None, dataset_id=i.dataset_id, source=src.name if src else None,
                monetary=bool(u.dims.get("BRL") == 1 and i.value_kind == "nominal"))


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/meta")
def meta(c: Ctx = Depends(ctx)):
    cat = read_catalog()
    n_ind = c.s.execute(select(Indicator.status, func.count()).group_by(Indicator.status)).all()
    last = c.s.scalar(select(func.max(IngestionRun.finished_at)).where(IngestionRun.status == "ok"))
    return dict(
        name="Atlas Econômico e Social do Brasil", version="0.1.0",
        dimensions=cat["dimensions"], levels=[dict(id=l, name=LEVEL_NAMES[l]) for l in LEVELS],
        indicators={s: n for s, n in n_ind}, counts=c.da.counts(),
        updated_at=last.isoformat(timespec="seconds") if last else None,
        start_year=settings.start_year,
    )


@router.get("/indicators")
def indicators(c: Ctx = Depends(ctx), dimension: str | None = None, level: str | None = None,
               frequency: str | None = None, status: str | None = None):
    q = (select(Indicator, Unit, Dataset, Source).join(Unit, Indicator.unit_id == Unit.id)
         .outerjoin(Dataset, Indicator.dataset_id == Dataset.id).outerjoin(Source, Dataset.source_id == Source.id)
         .order_by(Indicator.dimension, Indicator.sort))
    if dimension:
        q = q.where(Indicator.dimension == dimension)
    if frequency:
        q = q.where(Indicator.frequency == frequency)
    if status:
        q = q.where(Indicator.status == status)
    out = []
    for i, u, d, src in c.s.execute(q):
        if level and level.upper() not in (i.levels or []):
            continue
        row = _ind(i, u, d, src)
        if i.status == "disponivel":
            lvl = "MUN" if "MUN" in i.levels else i.levels[0]
            p = c.periods(i.id, lvl)
            row["period_min"], row["period_max"], row["n_periods"] = (p[0], p[-1], len(p)) if p else (None, None, 0)
        out.append(row)
    return out


@router.get("/indicators/{indicator_id}")
def indicator_detail(indicator_id: str, c: Ctx = Depends(ctx)):
    row = c.s.execute(
        select(Indicator, Unit, Dataset, Source).join(Unit, Indicator.unit_id == Unit.id)
        .outerjoin(Dataset, Indicator.dataset_id == Dataset.id).outerjoin(Source, Dataset.source_id == Source.id)
        .where(Indicator.id == indicator_id)).first()
    if not row:
        raise HTTPException(404, "Indicador não encontrado.")
    i, u, d, src = row
    out = _ind(i, u, d, src)
    m = c.s.get(Methodology, i.methodology_id) if i.methodology_id else None
    out["methodology"] = dict(id=m.id, title=m.title, body=m.body, version=m.version) if m else None
    out["coverage"] = []
    if i.status == "disponivel":
        leafs = c.da._leaf_ids(i.id)
        out["components"] = [dict(id=x, name=c.da.info(x)["name"]) for x in leafs if x != i.id]
        out["sources"] = c.da.provenance([c.da.info(x)["dataset_id"] for x in leafs])
        for lvl in i.levels:
            p = c.periods(i.id, lvl)
            if p:
                out["coverage"].append(dict(level=lvl, level_name=LEVEL_NAMES[lvl], period_min=p[0], period_max=p[-1],
                                            n_periods=len(p), periods=p))
        if not i.formula:
            out["revisions"] = c.s.scalar(select(func.count()).select_from(Observation).where(
                Observation.indicator_id == i.id, Observation.is_current.is_(False)))
    return out


@router.get("/sources")
def sources(c: Ctx = Depends(ctx)):
    out = []
    for src in c.s.scalars(select(Source).order_by(Source.name)):
        ds = []
        for d in sorted(src.datasets, key=lambda d: (d.status != "integrado", d.name)):
            run = c.s.execute(select(IngestionRun).where(IngestionRun.dataset_id == d.id, IngestionRun.status == "ok")
                              .order_by(IngestionRun.id.desc()).limit(1)).scalar()
            n = c.s.scalar(select(func.count()).select_from(Indicator).where(Indicator.dataset_id == d.id))
            ds.append(dict(id=d.id, name=d.name, endpoint=d.endpoint, format=d.format, access=d.access,
                           periodicity=d.periodicity, coverage=d.coverage, notes=d.notes, status=d.status, indicators=n,
                           publication=run.publication if run else None,
                           updated_at=run.finished_at.isoformat(timespec="seconds") if run and run.finished_at else None))
        out.append(dict(id=src.id, name=src.name, url=src.url, license=src.license, notes=src.notes, datasets=ds))
    return out


@router.get("/methodologies")
def methodologies(c: Ctx = Depends(ctx)):
    return [dict(id=m.id, title=m.title, body=m.body, version=m.version)
            for m in c.s.scalars(select(Methodology).order_by(Methodology.title))]


@router.get("/runs")
def runs(c: Ctx = Depends(ctx), limit: int = Query(50, le=200)):
    return [dict(id=r.id, pipeline=r.pipeline, dataset_id=r.dataset_id, status=r.status, publication=r.publication,
                 started_at=r.started_at.isoformat(timespec="seconds"),
                 finished_at=r.finished_at.isoformat(timespec="seconds") if r.finished_at else None,
                 rows_new=r.rows_new, rows_revised=r.rows_revised, rows_unchanged=r.rows_unchanged, error=r.error)
            for r in c.s.scalars(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(limit))]


def _terr(t: Territory, ufs: dict[str, str]) -> dict:
    return dict(code=t.code, level=t.level, name=t.name, sigla=t.sigla, uf_code=t.uf_code,
                uf=ufs.get(t.uf_code) if t.uf_code else None, regiao_code=t.regiao_code,
                rgint_code=t.rgint_code, rgi_code=t.rgi_code)


@router.get("/territories")
def territories(c: Ctx = Depends(ctx), level: str | None = None, q: str | None = None, uf: str | None = None,
                limit: int = Query(30, le=6000)):
    ufs = c.uf_siglas()
    st = select(Territory)
    if level:
        st = st.where(Territory.level == c.level(level))
    if uf:
        st = st.where(Territory.uf_code == uf)
    if q:
        n = normalize(q)
        st = st.where(or_(Territory.name_norm.like(f"{n}%"), Territory.name_norm.like(f"% {n}%"), Territory.code == q.strip()))
        # homônimos (município, região imediata e intermediária de mesmo nome): estado e município vêm primeiro
        rank = case({"BR": 0, "UF": 0, "MUN": 1, "REGIAO": 2, "RGI": 3, "RGINT": 4}, value=Territory.level, else_=5)
        st = st.order_by(Territory.name_norm.like(f"{n}%").desc(), func.length(Territory.name), rank, Territory.name)
    else:
        st = st.order_by(Territory.name)
    return [_terr(t, ufs) for t in c.s.scalars(st.limit(limit))]


@router.get("/territories/{code}")
def territory(code: str, c: Ctx = Depends(ctx)):
    t = c.territory(code)
    ufs = c.uf_siglas()
    out = _terr(t, ufs)
    parents = []
    for lvl, pc in (("RGI", t.rgi_code), ("RGINT", t.rgint_code), ("UF", t.uf_code), ("REGIAO", t.regiao_code)):
        if pc and pc != t.code:
            p = c.s.get(Territory, pc)
            if p:
                parents.append(dict(code=p.code, level=lvl, level_name=LEVEL_NAMES[lvl], name=p.name))
    if t.level != "BR":
        parents.append(dict(code="BR", level="BR", level_name="Brasil", name="Brasil"))
    out["parents"] = parents
    changes = []
    for ch in c.s.scalars(select(TerritoryChange).where(TerritoryChange.code == code).order_by(TerritoryChange.year)):
        rel = [dict(code=r, name=c.s.get(Territory, r).name) for r in ch.related_codes if c.s.get(Territory, r)]
        changes.append(dict(kind=ch.kind, year=ch.year, note=ch.note, related=rel))
    out["changes"] = changes
    out["first_population_year"] = c.s.scalar(select(func.min(Observation.period)).where(
        Observation.indicator_id == "populacao", Observation.territory_code == code, Observation.value.is_not(None)))
    if t.level in ("UF", "RGINT", "RGI"):
        child = {"UF": Territory.uf_code, "RGINT": Territory.rgint_code, "RGI": Territory.rgi_code}[t.level]
        out["n_municipios"] = c.s.scalar(select(func.count()).select_from(Territory).where(child == code, Territory.level == "MUN"))
    return out


@router.get("/geo/{level}")
def geo(level: str):
    level = level.upper()
    path = settings.geo_dir / f"{level}.geojson.gz"
    if not path.exists():
        raise HTTPException(404, "Malha não disponível. Execute: python -m atlas.cli ingest territorios")
    return Response(path.read_bytes(), media_type="application/geo+json",
                    headers={"Content-Encoding": "gzip", "Cache-Control": "public, max-age=86400"})
