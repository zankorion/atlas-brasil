"""Rotas de dados: mapa, séries históricas, perfis, comparadores e exportação."""
from __future__ import annotations

import csv
import io
import json
import math
from datetime import datetime

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select

from ..data import LEVEL_NAMES
from ..models import Indicator, Observation, TerritoryChange
from ..stats import core
from .deps import Ctx, ctx, named, split_codes

router = APIRouter(prefix="/api")


def _clean(v):
    return None if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v


def frame_at(c: Ctx, spec: str, level: str, period: str, real: str = "") -> tuple[pl.DataFrame, dict]:
    v = c.resolve(spec, level, [period], real=real)
    return v.result.df.filter(pl.col("period") == period).select("code", "value"), v.meta


@router.get("/periods")
def periods(var: str, level: str = "MUN", c: Ctx = Depends(ctx)):
    level = c.level(level)
    return dict(var=var, level=level, periods=c.periods(var, level))


@router.get("/map")
def map_data(var: str, level: str = "MUN", period: str | None = None, real: str = "",
             method: str = "quantis", k: int = Query(5, ge=3, le=9), uf: str | None = None, c: Ctx = Depends(ctx)):
    level = c.level(level)
    period = c.period_or_latest(var, level, period)
    df, meta = frame_at(c, var, level, period, real)
    full = named(c, df, level, uf)
    vals = [v for v in full["value"].to_list() if v is not None]
    return dict(
        meta=meta, level=level, level_name=LEVEL_NAMES[level], period=period, periods=c.periods(var, level),
        stats=core.describe(vals), breaks=core.classify(vals, method, k), method=method,
        n_inconsistent=len(c.da.flagged(var, level, period)),
        n_territories=full.height, n_missing=full.height - len(vals),
        values=[dict(code=r["code"], value=_clean(r["value"])) for r in full.select("code", "value").to_dicts()],
    )


def _series_for(c: Ctx, var: str, codes: list[str], real: bool):
    by_level: dict[str, list] = {}
    terrs = {}
    for code in codes:
        t = c.territory(code)
        terrs[code] = t
        by_level.setdefault(t.level, []).append(code)
    ufs = c.uf_siglas()
    series, meta = [], None
    for level, cs in by_level.items():
        v = c.resolve(var, level, None, cs, real)
        meta = meta or v.meta
        df = v.result.df.sort("period")
        for code in cs:
            pts = df.filter(pl.col("code") == code).select("period", "value").to_dicts()
            # remove ausências nas pontas (antes do início e depois do fim efetivos da série); lacunas internas ficam
            while pts and pts[0]["value"] is None:
                pts.pop(0)
            while pts and pts[-1]["value"] is None:
                pts.pop()
            t = terrs[code]
            series.append(dict(code=code, name=t.name, level=level, uf=ufs.get(t.uf_code) if t.level not in ("UF", "BR", "REGIAO") else None,
                               points=[dict(period=p["period"], value=_clean(p["value"])) for p in pts]))
    series.sort(key=lambda s: codes.index(s["code"]))
    return series, meta


@router.get("/series")
def series(var: str, codes: str = "BR", real: str = "", c: Ctx = Depends(ctx)):
    cs = split_codes(codes)
    out, meta = _series_for(c, var, cs, real)
    changes = [dict(code=ch.code, year=ch.year, kind=ch.kind, note=ch.note)
               for ch in c.s.scalars(select(TerritoryChange).where(TerritoryChange.code.in_(cs)))]
    return dict(meta=meta, series=out, territory_changes=changes)


def _profile_indicators(c: Ctx, level: str) -> list[Indicator]:
    q = select(Indicator).where(Indicator.status == "disponivel", Indicator.frequency == "A").order_by(Indicator.dimension, Indicator.sort)
    return [i for i in c.s.scalars(q) if level in (i.levels or [])]


@router.get("/profile/{code}")
def profile(code: str, real: str = "", c: Ctx = Depends(ctx)):
    """Perfil territorial: último valor de cada indicador, com referência de período, UF, Brasil e posição."""
    t = c.territory(code)
    rows = []
    for ind in _profile_indicators(c, t.level):
        ps = c.periods(ind.id, t.level)
        if not ps:
            continue
        # último período em que ESTE território tem valor (pode diferir do último período do indicador)
        var = c.resolve(ind.id, t.level, None, [code], real)
        own = var.result.df.filter(pl.col("value").is_not_null()).sort("period")
        info = c.da.info(ind.id)
        base = dict(id=ind.id, name=ind.name, short_name=ind.short_name or ind.name, dimension=ind.dimension,
                    unit=var.meta["unit"], moeda=var.meta.get("moeda"), real=var.meta["real"], decimals=ind.decimals, nature=ind.nature, percent=info["percent"])
        if own.height == 0:
            bad = c.s.scalar(select(func.max(Observation.period)).where(
                Observation.indicator_id.in_(c.da._leaf_ids(ind.id)), Observation.territory_code == code,
                Observation.is_current.is_(True), Observation.flag == "inc"))
            rows.append({**base, "period": None, "value": None, "missing_reason":
                         f"A declaração de {bad} foi deixada de fora por inconsistência contábil (ver metodologia)." if bad
                         else "Sem observação para este território nesta base."})
            continue
        period = own["period"][-1]
        value = own["value"][-1]
        df, _ = frame_at(c, ind.id, t.level, period, real)
        vals = df.filter(pl.col("value").is_not_null())
        rank = int(vals.filter(pl.col("value") > value).height) + 1 if t.level != "BR" else None
        row = {**base, "period": period, "value": _clean(value), "rank": rank, "rank_of": vals.height if rank else None,
               "first_period": own["period"][0], "stale": period != ps[-1]}
        for key, lvl, pc in (("uf_value", "UF", t.uf_code if t.level in ("MUN", "RGI", "RGINT") else None), ("br_value", "BR", "BR" if t.level != "BR" else None)):
            if pc and lvl in (ind.levels or []):
                d = c.resolve(ind.id, lvl, [period], [pc], real).result.df
                row[key] = _clean(d["value"][0]) if d.height else None
        rows.append(row)
    return dict(code=code, level=t.level, indicators=rows)


@router.get("/similar/{code}")
def similar(code: str, n: int = Query(6, ge=1, le=20), real: str = "", c: Ctx = Depends(ctx)):
    """Territórios semelhantes por porte populacional e PIB per capita (distância em escala logarítmica padronizada)."""
    t = c.territory(code)
    if t.level == "BR":
        return dict(basis=None, items=[])
    pp = [p for p in c.periods("pib_per_capita", t.level)]
    if not pp:
        return dict(basis=None, items=[])
    period = pp[-1]
    pop, _ = frame_at(c, "populacao", t.level, period)
    pib, _ = frame_at(c, "pib_per_capita", t.level, period)
    df = pop.rename({"value": "pop"}).join(pib.rename({"value": "pibpc"}), on="code").filter(
        (pl.col("pop") > 0) & (pl.col("pibpc") > 0))
    if df.filter(pl.col("code") == code).height == 0:
        return dict(basis=None, items=[])
    df = df.with_columns(pl.col("pop").log().alias("lp"), pl.col("pibpc").log().alias("lg"))
    df = df.with_columns(((pl.col("lp") - pl.col("lp").mean()) / pl.col("lp").std()).alias("zp"),
                         ((pl.col("lg") - pl.col("lg").mean()) / pl.col("lg").std()).alias("zg"))
    me = df.filter(pl.col("code") == code)
    df = df.with_columns((((pl.col("zp") - me["zp"][0]) ** 2 + (pl.col("zg") - me["zg"][0]) ** 2) ** 0.5).alias("dist"))
    top = df.filter(pl.col("code") != code).sort("dist").head(n)
    ufs = c.uf_siglas()
    names = c.terr(t.level)
    top = top.join(names, on="code")
    # A semelhança é calculada em reais (a conversão não muda a ordem); só o valor exibido segue a moeda escolhida.
    shown, shown_meta = frame_at(c, "pib_per_capita", t.level, period, real)
    top = top.join(shown.rename({"value": "pibpc_shown"}), on="code", how="left")
    return dict(
        basis=f"População e PIB per capita de {period} (distância euclidiana em logaritmos padronizados, mesmo nível territorial).",
        period=period, pib_per_capita_unit=shown_meta["unit"],
        items=[dict(code=r["code"], name=r["name"], uf=ufs.get(r["uf"]), populacao=r["pop"], pib_per_capita=_clean(r["pibpc_shown"]),
                    distance=round(r["dist"], 3)) for r in top.to_dicts()])


@router.get("/compare")
def compare(vars: str, codes: str, period: str | None = None, real: str = "", c: Ctx = Depends(ctx)):
    """Tabela comparativa: vários indicadores × vários territórios, com o período de referência de cada célula."""
    cs = split_codes(codes)
    specs = [v for v in vars.split(";") if v.strip()][:12]
    terrs = {code: c.territory(code) for code in cs}
    ufs = c.uf_siglas()
    out = []
    for spec in specs:
        cells, meta = {}, None
        for code, t in terrs.items():
            v = c.resolve(spec, t.level, [period] if period else None, [code], real)
            meta = meta or v.meta
            d = v.result.df.filter(pl.col("value").is_not_null()).sort("period")
            cells[code] = dict(value=_clean(d["value"][-1]), period=d["period"][-1]) if d.height else dict(value=None, period=period)
        ref = next((x["value"] for x in cells.values() if x["value"] not in (None, 0)), None)
        first = cells[cs[0]]["value"]
        for code in cs:
            v = cells[code]["value"]
            cells[code]["rel_first"] = _clean((v / first - 1) * 100) if v is not None and first not in (None, 0) else None
        out.append(dict(meta=meta, cells=cells, mixed_periods=len({x["period"] for x in cells.values() if x["value"] is not None}) > 1))
        _ = ref
    return dict(territories=[dict(code=code, name=t.name, level=t.level, uf=ufs.get(t.uf_code) if t.level == "MUN" else None)
                             for code, t in terrs.items()], rows=out, period=period)


@router.get("/historical")
def historical(var: str, p0: str, p1: str, level: str = "UF", real: str = "", uf: str | None = None,
               method: str | None = None, k: int = Query(5, ge=2, le=9), c: Ctx = Depends(ctx)):
    """Comparador histórico: variação entre dois períodos por território, sinalizando mudanças de limites."""
    level = c.level(level)
    if p0 >= p1:
        raise HTTPException(422, "O período inicial deve ser anterior ao final.")
    v = c.resolve(var, level, [p0, p1], real=real)
    df = v.result.df
    a = df.filter(pl.col("period") == p0).select("code", pl.col("value").alias("v0"))
    b = df.filter(pl.col("period") == p1).select("code", pl.col("value").alias("v1"))
    j = named(c, a.join(b, on="code", how="full", coalesce=True), level, uf)
    years = (int(p1[:4]) - int(p0[:4])) + ((int(p1[5:]) - int(p0[5:])) / 12 if "-" in p0 else 0)
    changed = {}
    if level == "MUN":
        for ch in c.s.scalars(select(TerritoryChange).where(TerritoryChange.year > int(p0[:4]), TerritoryChange.year <= int(p1[:4]))):
            changed.setdefault(ch.code, []).append(ch.note)
    ufs = c.uf_siglas()
    rows = []
    for r in j.to_dicts():
        v0, v1 = _clean(r["v0"]), _clean(r["v1"])
        absd = v1 - v0 if v0 is not None and v1 is not None else None
        pct = (v1 / v0 - 1) * 100 if absd is not None and v0 > 0 else None
        cagr = ((v1 / v0) ** (1 / years) - 1) * 100 if pct is not None and v1 > 0 and years > 0 else None
        rows.append(dict(code=r["code"], name=r["name"], uf=ufs.get(r["uf"]) if level != "UF" else None, v0=v0, v1=v1,
                         abs=_clean(absd), pct=_clean(pct), cagr=_clean(cagr), boundary_change=changed.get(r["code"])))
    pcts = [r["pct"] for r in rows if r["pct"] is not None]
    # Limites de classe da própria variação (em % e em diferença absoluta), para o mapa obedecer à classificação escolhida.
    breaks = None
    if method:
        if method not in ("jenks", "quantis", "iguais", "geometrico"):
            raise HTTPException(422, f"Método de classificação inválido: {method}.")
        breaks = dict(pct=core.classify(pcts, method, k), abs=core.classify([r["abs"] for r in rows if r["abs"] is not None], method, k))
    return dict(breaks=breaks, method=method, meta=v.meta, level=level, p0=p0, p1=p1, years=years, rows=rows, stats=core.describe(pcts),
                n_missing=sum(1 for r in rows if r["abs"] is None), n_boundary_changes=len(changed),
                periods=c.periods(var, level))


# ------------------------------------------------------------------ exportação
def export_table(c: Ctx, specs: list[str], level: str, periods: list[str] | None, codes: list[str] | None,
                 real: str | bool, uf: str | None) -> tuple[list[dict], list[dict]]:
    ufs = c.uf_siglas()
    names = c.terr(level)
    if uf and level in ("MUN", "RGI", "RGINT"):
        names = names.filter(pl.col("uf") == uf)
    rows, metas = [], []
    for spec in specs:
        v = c.resolve(spec, level, periods, codes, real)
        metas.append(v.meta)
        df = v.result.df.join(names, on="code", how="inner").sort("code", "period")
        iid = v.meta["id"] or v.meta["spec"]
        for r in df.to_dicts():
            rows.append(dict(indicador_id=iid, indicador=v.meta["name"], codigo_ibge=r["code"], territorio=r["name"],
                             uf=ufs.get(r["uf"]) if r["uf"] else None, nivel=level, periodo=r["period"],
                             valor=_clean(r["value"]), unidade=v.meta["unit"],
                             precos="constantes (IPCA)" if v.meta["real"] else {"usd": "convertidos em dólares (câmbio do período)", "ouro": "convertidos em gramas de ouro (cotação do período)"}.get(v.meta.get("moeda")) or ("correntes" if "R$" in v.meta["unit"] else None)))
    return rows, metas


def export_metadata(metas: list[dict], level: str) -> list[dict]:
    out = []
    for m in metas:
        out.append(dict(
            indicador_id=m["id"] or m["spec"], indicador=m["name"], unidade=m["unit"], natureza=m["nature"],
            periodicidade={"A": "anual", "M": "mensal"}.get(m["frequency"], m["frequency"]),
            cobertura_geografica=LEVEL_NAMES[level], formula=m["formula"],
            transformacao="; ".join(m["notes"]) or ("Indicador derivado: " + m["formula"] if m["formula"] else "Sem transformação (valor da fonte, em unidades-base)"),
            fontes="; ".join(f"{s['source']} — {s['dataset']}" for s in m["sources"]),
            publicacao="; ".join(s["publication"] or "" for s in m["sources"]),
            atualizado_em="; ".join(s["updated_at"] or "" for s in m["sources"]),
            limitacoes=m["limitations"], metodologia_id=m["methodology_id"],
            divisoes_por_zero=m["div_zero"],
        ))
    return out


@router.get("/export")
def export(vars: str, level: str = "MUN", periods: str | None = None, codes: str | None = None, real: str = "",
           uf: str | None = None, format: str = "csv", c: Ctx = Depends(ctx)):
    level = c.level(level)
    specs = [v for v in vars.split(";") if v.strip()][:10]
    if not specs:
        raise HTTPException(422, "Informe ao menos um indicador.")
    ps = [p for p in periods.split(",") if p] if periods else None
    cs = [x for x in codes.split(",") if x] if codes else None
    rows, metas = export_table(c, specs, level, ps, cs, real, uf)
    md = export_metadata(metas, level)
    stamp = datetime.now().strftime("%Y%m%d")
    fname = f"atlas_{(metas[0]['id'] or 'personalizado')}_{level.lower()}_{stamp}"
    cols = ["indicador_id", "indicador", "codigo_ibge", "territorio", "uf", "nivel", "periodo", "valor", "unidade", "precos"]
    if format == "json":
        body = json.dumps(dict(gerado_em=datetime.now().isoformat(timespec="seconds"),
                               projeto="Atlas Econômico e Social do Brasil",
                               observacao="Valores ausentes (null) não equivalem a zero.",
                               metadados=md, dados=rows), ensure_ascii=False)
        return Response(body, media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.json"'})
    if format == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "dados"
        ws.append(cols)
        for r in rows:
            ws.append([r[k] for k in cols])
        wm = wb.create_sheet("metadados")
        if md:
            wm.append(list(md[0].keys()))
            for m in md:
                wm.append([str(v) if v is not None else None for v in m.values()])
        wm.append([])
        wm.append(["Gerado em", datetime.now().isoformat(timespec="seconds")])
        wm.append(["Observação", "Células vazias são valores ausentes — não equivalem a zero."])
        buf = io.BytesIO()
        wb.save(buf)
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})
    if format != "csv":
        raise HTTPException(422, "Formato inválido. Opções: csv, xlsx, json.")
    buf = io.StringIO()
    buf.write("# Atlas Econômico e Social do Brasil — exportação de dados\n")
    buf.write(f"# Gerado em: {datetime.now().isoformat(timespec='seconds')}\n")
    buf.write("# Valores vazios são ausências (dado não disponível ou suprimido) — não equivalem a zero.\n")
    for m in md:
        for k, v in m.items():
            if v not in (None, "", 0):
                buf.write(f"# {m['indicador_id']} | {k}: {str(v).replace(chr(10), ' ')}\n")
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
