"""Laboratório de análise: dispersão, correlação, regressão, rankings, distribuições, grupos e busca avançada."""
from __future__ import annotations

import math

import numpy as np
import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..data import LEVEL_NAMES
from ..stats import core
from ..stats.formula import FormulaError, check_units, references
from .data_routes import _clean, frame_at
from .deps import Ctx, ctx, named

router = APIRouter(prefix="/api/lab")

CAUSALITY = ("Correlação e regressão descrevem associação estatística entre agregados territoriais. Não indicam "
             "causalidade nem permitem inferir comportamentos individuais (falácia ecológica).")


class ScatterReq(BaseModel):
    x: str
    y: str
    level: str = "MUN"
    period: str | None = None
    period_y: str | None = None
    real: bool = False
    log_x: bool = False
    log_y: bool = False
    uf: str | None = None
    pop_min: float | None = Field(None, ge=0)
    size: str | None = None  # variável opcional para o tamanho do ponto


@router.post("/scatter")
def scatter(req: ScatterReq, c: Ctx = Depends(ctx)):
    level = c.level(req.level)
    px = c.period_or_latest(req.x, level, req.period)
    py = req.period_y or (req.period if req.period else None)
    if py is None:
        py = px if px in c.periods(req.y, level) else c.period_or_latest(req.y, level, None)
    dx, mx = frame_at(c, req.x, level, px, req.real)
    dy, my = frame_at(c, req.y, level, py, req.real)
    df = named(c, dx.rename({"value": "x"}).join(dy.rename({"value": "y"}), on="code", how="full", coalesce=True), level, req.uf)
    n_total = df.height
    notes = []
    if req.pop_min:
        pp = c.periods("populacao", level)
        ppop = px if px in pp else (max([p for p in pp if p <= px[:4]], default=pp[-1]) if pp else None)
        if ppop:
            pop, _ = frame_at(c, "populacao", level, ppop)
            df = df.join(pop.rename({"value": "_pop"}), on="code", how="left").filter(pl.col("_pop") >= req.pop_min)
            notes.append(f"Filtro: população de {ppop} ≥ {req.pop_min:,.0f}.".replace(",", "."))
    n_scope = df.height
    miss_x = df.filter(pl.col("x").is_null() & pl.col("y").is_not_null()).height
    miss_y = df.filter(pl.col("y").is_null() & pl.col("x").is_not_null()).height
    miss_both = df.filter(pl.col("x").is_null() & pl.col("y").is_null()).height
    ok = df.filter(pl.col("x").is_not_null() & pl.col("y").is_not_null())
    nonpos = 0
    if req.log_x:
        nonpos += ok.filter(pl.col("x") <= 0).height
        ok = ok.filter(pl.col("x") > 0)
    if req.log_y:
        nonpos += ok.filter(pl.col("y") <= 0).height
        ok = ok.filter(pl.col("y") > 0)
    x = np.asarray(ok["x"].to_list(), float)
    y = np.asarray(ok["y"].to_list(), float)
    tx, ty = (np.log(x) if req.log_x else x), (np.log(y) if req.log_y else y)
    ufs = c.uf_siglas()
    if px != py:
        notes.append(f"As variáveis referem-se a períodos diferentes (X: {px}; Y: {py}).")
    return dict(
        x=mx, y=my, level=level, level_name=LEVEL_NAMES[level], period_x=px, period_y=py,
        log_x=req.log_x, log_y=req.log_y,
        sample=dict(n=int(ok.height), n_territories=n_total, n_in_scope=n_scope, missing_x=miss_x, missing_y=miss_y,
                    missing_both=miss_both, dropped_nonpositive_log=nonpos),
        correlation=core.correlation(tx, ty), regression=core.ols(tx, ty),
        regression_note=("Regressão estimada sobre " + ("ln(X)" if req.log_x else "X") + " e " + ("ln(Y)" if req.log_y else "Y") + "."),
        notes=notes, warning=CAUSALITY,
        points=[dict(code=r["code"], name=r["name"], uf=ufs.get(r["uf"]) if level != "UF" else None, x=r["x"], y=r["y"])
                for r in ok.select("code", "name", "uf", "x", "y").to_dicts()],
    )


class FormulaReq(BaseModel):
    expr: str
    level: str = "MUN"


@router.post("/formula")
def formula(req: FormulaReq, c: Ctx = Depends(ctx)):
    """Valida uma fórmula (sintaxe, referências, unidades) e informa cobertura e resumo do último período."""
    level = c.level(req.level)
    try:
        refs = references(req.expr)
        unit = check_units(req.expr, c.da)
    except FormulaError as e:
        return dict(valid=False, error=str(e))
    spec = "=" + req.expr
    try:
        periods = c.periods(spec, level)
    except HTTPException as e:
        return dict(valid=False, error=e.detail)
    out = dict(valid=True, spec=spec, unit=unit.label(), level=level, periods=periods,
               references=[dict(id=r, name=c.da.info(r)["name"], unit=c.da.info(r)["unit_label"]) for r in refs])
    if periods:
        try:
            df, meta = frame_at(c, spec, level, periods[-1])
        except HTTPException as e:
            return dict(valid=False, error=e.detail)
        vals = [v for v in df["value"].to_list() if v is not None]
        out.update(preview_period=periods[-1], stats=core.describe(vals), div_zero=meta["div_zero"],
                   n_missing=c.terr(level).height - len(vals))
    else:
        out["warning"] = "Não há período em que todos os componentes tenham dados neste nível territorial."
    return out


@router.get("/ranking")
def ranking(var: str, level: str = "MUN", period: str | None = None, real: bool = False, uf: str | None = None,
            n: int = Query(20, ge=1, le=6000), order: str = "desc", pop_min: float | None = None, c: Ctx = Depends(ctx)):
    level = c.level(level)
    period = c.period_or_latest(var, level, period)
    df, meta = frame_at(c, var, level, period, real)
    full = named(c, df, level, uf)
    if pop_min:
        pp = c.periods("populacao", level)
        ppop = period if period in pp else (pp[-1] if pp else None)
        if ppop:
            pop, _ = frame_at(c, "populacao", level, ppop)
            full = full.join(pop.rename({"value": "_pop"}), on="code", how="left").filter(pl.col("_pop") >= pop_min)
    ok = full.filter(pl.col("value").is_not_null()).sort("value", descending=(order != "asc"))
    ufs = c.uf_siglas()
    return dict(meta=meta, level=level, period=period, n_ranked=ok.height, n_missing=full.height - ok.height,
                periods=c.periods(var, level),
                rows=[dict(rank=i + 1, code=r["code"], name=r["name"], uf=ufs.get(r["uf"]) if level != "UF" else None, value=r["value"])
                      for i, r in enumerate(ok.head(n).to_dicts())])


@router.get("/distribution")
def distribution(var: str, level: str = "MUN", period: str | None = None, real: bool = False, uf: str | None = None,
                 bins: int = Query(30, ge=5, le=80), log: bool = False, weight_pop: bool = False, c: Ctx = Depends(ctx)):
    """Histograma, estatísticas descritivas e medidas de desigualdade territorial."""
    level = c.level(level)
    period = c.period_or_latest(var, level, period)
    df, meta = frame_at(c, var, level, period, real)
    full = named(c, df, level, uf)
    ok = full.filter(pl.col("value").is_not_null())
    weights, wnote = None, None
    if weight_pop:
        pp = c.periods("populacao", level)
        if period in pp:
            pop, _ = frame_at(c, "populacao", level, period)
            ok = ok.join(pop.rename({"value": "_pop"}), on="code", how="inner").filter(pl.col("_pop") > 0)
            weights = ok["_pop"].to_list()
            wnote = f"Medidas de desigualdade ponderadas pela população de {period}."
        else:
            wnote = f"Sem população para {period}: medidas não ponderadas."
    vals = np.asarray(ok["value"].to_list(), float)
    hv = vals
    dropped = 0
    if log:
        dropped = int((vals <= 0).sum())
        hv = np.log10(vals[vals > 0])
    hist = []
    if hv.size:
        counts, edges = np.histogram(hv, bins=bins)
        for i, n_ in enumerate(counts):
            lo, hi = float(edges[i]), float(edges[i + 1])
            hist.append(dict(lo=10**lo if log else lo, hi=10**hi if log else hi, n=int(n_)))
    return dict(meta=meta, level=level, period=period, periods=c.periods(var, level), log=log,
                stats=core.describe(vals), inequality=core.inequality(vals, weights), weight_note=wnote,
                histogram=hist, n_missing=full.height - int(full.filter(pl.col("value").is_not_null()).height),
                dropped_nonpositive_log=dropped,
                inequality_note="Gini e Theil medem a desigualdade ENTRE territórios do indicador; valores negativos são excluídos.")


@router.get("/groups")
def groups(var: str, level: str = "MUN", period: str | None = None, real: bool = False, by: str = "regiao",
           c: Ctx = Depends(ctx)):
    """Comparação de grupos territoriais (por grande região ou UF): distribuição do indicador em cada grupo."""
    level = c.level(level)
    if by not in ("regiao", "uf"):
        raise HTTPException(422, "Agrupamento inválido: use regiao ou uf.")
    if level in ("BR", "REGIAO") or (level == "UF" and by == "uf"):
        raise HTTPException(422, "Agrupamento incompatível com o nível territorial escolhido.")
    period = c.period_or_latest(var, level, period)
    df, meta = frame_at(c, var, level, period, real)
    full = named(c, df, level)
    gl = "REGIAO" if by == "regiao" else "UF"
    gnames = {r["code"]: r["name"] for r in c.terr(gl).to_dicts()}
    agg = {}
    try:  # valor do próprio agregado (ex.: PIB per capita da região), quando o indicador existe nesse nível
        gdf, _ = frame_at(c, var, gl, period, real)
        agg = dict(zip(gdf["code"].to_list(), gdf["value"].to_list()))
    except HTTPException:
        pass
    out = []
    for key, sub in full.group_by(by):
        g = key[0] if isinstance(key, tuple) else key
        vals = [v for v in sub["value"].to_list() if v is not None]
        out.append(dict(code=g, name=gnames.get(g, g), n_missing=sub.height - len(vals), aggregate_value=_clean(agg.get(g)),
                        **core.describe(vals)))
    out.sort(key=lambda r: (r.get("median") is None, -(r.get("median") or 0)))
    return dict(meta=meta, level=level, period=period, by=by, groups=out, periods=c.periods(var, level),
                note="Mediana, média e quantis referem-se à distribuição entre os territórios do grupo (não ponderada). "
                     "“Valor do agregado” é o indicador calculado para o grupo como um todo.")


class Condition(BaseModel):
    var: str
    op: str = ">"  # > >= < <= entre
    value: float | None = None
    value2: float | None = None
    ref: str | None = None  # mediana | media | br
    period: str | None = None
    real: bool = False


class SearchReq(BaseModel):
    level: str = "MUN"
    conditions: list[Condition] = Field(min_length=1, max_length=8)
    uf: str | None = None
    limit: int = Field(200, ge=1, le=6000)


@router.post("/search")
def search(req: SearchReq, c: Ctx = Depends(ctx)):
    """Pesquisa avançada: combina condições (E lógico). Territórios sem dado em alguma condição não são retornados
    e são contados à parte."""
    level = c.level(req.level)
    base = c.terr(level)
    if req.uf and level in ("MUN", "RGI", "RGINT"):
        base = base.filter(pl.col("uf") == req.uf)
    df = base
    desc = []
    missing_any = pl.lit(False)
    passed = pl.lit(True)
    for i, cond in enumerate(req.conditions):
        period = c.period_or_latest(cond.var, level, cond.period)
        d, meta = frame_at(c, cond.var, level, period, cond.real)
        col = f"v{i}"
        df = df.join(d.rename({"value": col}), on="code", how="left")
        thr = cond.value
        ref_label = None
        if cond.ref:
            vals = [v for v in d["value"].to_list() if v is not None]
            if cond.ref == "mediana":
                thr, ref_label = (float(np.median(vals)) if vals else None), f"mediana dos territórios ({LEVEL_NAMES[level]})"
            elif cond.ref == "media":
                thr, ref_label = (float(np.mean(vals)) if vals else None), f"média simples dos territórios ({LEVEL_NAMES[level]})"
            elif cond.ref == "br":
                b, _ = frame_at(c, cond.var, "BR", period, cond.real)
                thr, ref_label = (b["value"][0] if b.height else None), "valor do Brasil"
            else:
                raise HTTPException(422, f"Referência inválida: {cond.ref}.")
        if thr is None or (isinstance(thr, float) and math.isnan(thr)):
            raise HTTPException(422, f"Condição {i + 1}: informe um valor ou uma referência com dados disponíveis.")
        x = pl.col(col)
        if cond.op == ">":
            e = x > thr
        elif cond.op == ">=":
            e = x >= thr
        elif cond.op == "<":
            e = x < thr
        elif cond.op == "<=":
            e = x <= thr
        elif cond.op == "entre":
            if cond.value2 is None:
                raise HTTPException(422, f"Condição {i + 1}: informe o limite superior.")
            e = (x >= thr) & (x <= cond.value2)
        else:
            raise HTTPException(422, f"Operador inválido: {cond.op}.")
        missing_any = missing_any | x.is_null()
        passed = passed & e.fill_null(False)
        desc.append(dict(column=col, meta=meta, period=period, op=cond.op, threshold=thr, threshold2=cond.value2,
                         ref=ref_label))
    n_missing = df.filter(missing_any).height
    res = df.filter(passed)
    ufs = c.uf_siglas()
    rows = []
    for r in res.head(req.limit).to_dicts():
        rows.append(dict(code=r["code"], name=r["name"], uf=ufs.get(r["uf"]) if level != "UF" else None,
                         values=[_clean(r[f"v{i}"]) for i in range(len(req.conditions))]))
    return dict(level=level, conditions=desc, n_scope=df.height, n_match=res.height, n_excluded_missing=n_missing,
                rows=rows, truncated=res.height > req.limit)
