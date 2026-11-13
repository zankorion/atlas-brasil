"""Acesso a dados para a API: carrega observações vigentes e resolve variáveis (indicador ou fórmula)."""
from __future__ import annotations

from dataclasses import dataclass

import polars as pl
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Dataset, Indicator, IngestionRun, Observation, Source, Territory, Unit
from .stats.formula import FormulaError, Result, UnitT, evaluate

LEVELS = ["BR", "REGIAO", "UF", "RGINT", "RGI", "MUN"]
LEVEL_NAMES = {"BR": "Brasil", "REGIAO": "Grandes regiões", "UF": "Unidades da Federação",
               "RGINT": "Regiões geográficas intermediárias", "RGI": "Regiões geográficas imediatas", "MUN": "Municípios"}
SCHEMA = {"code": pl.String, "period": pl.String, "value": pl.Float64}
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


@dataclass
class Variable:
    spec: str
    name: str
    unit: str
    result: Result
    meta: dict


class DataAccess:
    def __init__(self, session: Session):
        self.s = session
        self._info: dict[str, dict | None] = {}
        self._defl: dict[tuple[str, str], tuple[dict[str, float], str]] = {}

    # ---------------------------------------------------------- Loader (fórmulas)
    def info(self, indicator_id: str) -> dict | None:
        if indicator_id not in self._info:
            row = self.s.execute(
                select(Indicator, Unit).join(Unit, Indicator.unit_id == Unit.id).where(Indicator.id == indicator_id)
            ).first()
            if row is None:
                self._info[indicator_id] = None
            else:
                i, u = row
                self._info[indicator_id] = dict(
                    id=i.id, name=i.name, short_name=i.short_name, formula=i.formula, frequency=i.frequency,
                    stock_flow=i.stock_flow, value_kind=i.value_kind, status=i.status, dims=u.dims, percent=u.percent,
                    unit_label=u.label, nature=i.nature, dataset_id=i.dataset_id, methodology_id=i.methodology_id,
                    levels=i.levels, decimals=i.decimals, limitations=i.limitations, breaks=i.breaks,
                    dimension=i.dimension, description=i.description)
        return self._info[indicator_id]

    def load(self, indicator_id: str, level: str, periods: list[str] | None, codes: list[str] | None) -> pl.DataFrame:
        o = Observation
        q = select(o.territory_code, o.period, o.value).where(
            o.indicator_id == indicator_id, o.level == level, o.is_current.is_(True))
        if periods is not None:
            if not periods:
                return pl.DataFrame(schema=SCHEMA)
            q = q.where(o.period.in_(periods))
        if codes is not None and len(codes) <= 400:
            q = q.where(o.territory_code.in_(codes))
        rows = self.s.execute(q).all()
        df = pl.DataFrame(rows, schema=SCHEMA, orient="row") if rows else pl.DataFrame(schema=SCHEMA)
        if codes is not None and len(codes) > 400:
            df = df.filter(pl.col("code").is_in(codes))
        return df

    def deflator(self, freq: str, stock_flow: str) -> tuple[dict[str, float], str]:
        key = (freq, stock_flow)
        if key in self._defl:
            return self._defl[key]
        idx = dict(self.s.execute(select(Observation.period, Observation.value).where(
            Observation.indicator_id == "ipca_indice", Observation.is_current.is_(True))).all())
        if not idx:
            raise FormulaError("Deflator indisponível: carregue as séries do SGS (IPCA) antes de usar valores reais.")
        if freq == "M":
            base = max(idx)
            out = {p: idx[base] / v for p, v in idx.items()}
            label = f"{MONTHS[int(base[5:]) - 1]}/{base[:4]}"
        elif stock_flow == "estoque":
            dec = {p[:4]: v for p, v in idx.items() if p.endswith("-12")}
            base = max(dec)
            out = {y: dec[base] / v for y, v in dec.items()}
            label = f"dezembro de {base}"
        else:
            by_year: dict[str, list[float]] = {}
            for p, v in idx.items():
                by_year.setdefault(p[:4], []).append(v)
            avg = {y: sum(v) / 12 for y, v in by_year.items() if len(v) == 12}
            base = max(avg)
            out = {y: avg[base] / v for y, v in avg.items()}
            label = f"{base} (média anual)"
        self._defl[key] = (out, label)
        return self._defl[key]

    # ------------------------------------------------------------------ variáveis
    def resolve(self, spec: str, level: str, periods: list[str] | None = None, codes: list[str] | None = None,
                real: bool = False) -> Variable:
        """`spec` é o id de um indicador do catálogo ou '=expressão' (indicador personalizado)."""
        spec = spec.strip()
        custom = spec.startswith("=")
        expr = spec[1:] if custom else spec
        info = None if custom else self.info(expr)
        if not custom and info is None:
            raise FormulaError(f"Indicador desconhecido: “{expr}”.")
        if info and info["status"] == "planejado":
            raise FormulaError(f"“{info['name']}” está catalogado, mas ainda não possui dados integrados.")
        if info and info["levels"] and level not in info["levels"]:
            raise FormulaError(f"“{info['name']}” não está disponível no nível {LEVEL_NAMES.get(level, level)}.")
        can_deflate = False
        if real:
            probe = evaluate(expr, self, level, [], codes)
            can_deflate = probe.nominal and dict(probe.unit.dims).get("BRL", 0) == 1
        res = evaluate(f"real({expr})" if can_deflate else expr, self, level, periods, codes)
        if info:
            unit_label, name = info["unit_label"], info["name"]
            unit = UnitT.of(info["dims"], info["percent"])
        else:
            unit, unit_label, name = res.unit, res.unit.label(), f"Indicador personalizado: {expr}"
        comps = [self.info(c) for c in res.components]
        notes = list(dict.fromkeys(res.notes))
        if res.out_of_range:
            notes.append(f"{res.out_of_range} observação(ões) com participação fora de 0–100% (parte negativa ou maior que o total na fonte) foram tratadas como ausentes.")
        if real and not can_deflate:
            notes.append("Deflacionamento não aplicado: o indicador não é um valor monetário nominal.")
        meta = dict(
            spec=spec, id=None if custom else expr, name=name, short_name=(info or {}).get("short_name") or name,
            unit=unit_label, custom=custom, formula=expr if custom else (info or {}).get("formula"),
            nature="personalizado" if custom else info["nature"], frequency=res.freq, real=can_deflate,
            decimals=(info or {}).get("decimals", 2), percent=unit.percent,
            limitations=(info or {}).get("limitations"), breaks=(info or {}).get("breaks") or [],
            methodology_id=(info or {}).get("methodology_id"), div_zero=res.div_zero, out_of_range=res.out_of_range, notes=notes,
            components=[dict(id=c["id"], name=c["name"], dataset_id=c["dataset_id"]) for c in comps if c],
            sources=self.provenance([c["dataset_id"] for c in comps if c]),
        )
        return Variable(spec, name, unit_label, res, meta)

    def provenance(self, dataset_ids: list[str | None]) -> list[dict]:
        out = []
        for did in dict.fromkeys(d for d in dataset_ids if d):
            row = self.s.execute(select(Dataset, Source).join(Source).where(Dataset.id == did)).first()
            if not row:
                continue
            d, src = row
            run = self.s.execute(select(IngestionRun).where(IngestionRun.dataset_id == did, IngestionRun.status == "ok")
                                 .order_by(IngestionRun.finished_at.desc()).limit(1)).scalar()
            out.append(dict(dataset_id=d.id, dataset=d.name, source=src.name, endpoint=d.endpoint, license=src.license,
                            publication=run.publication if run else None,
                            updated_at=run.finished_at.isoformat(timespec="seconds") if run and run.finished_at else None))
        return out

    # ------------------------------------------------------------------ cobertura
    def periods_of(self, spec: str, level: str) -> list[str]:
        """Períodos com ao menos um valor não ausente para a variável no nível dado."""
        ids = self._leaf_ids(spec)
        if not ids:
            return []
        sets = []
        for i in ids:
            q = select(Observation.period).where(Observation.indicator_id == i, Observation.level == level,
                                                 Observation.is_current.is_(True), Observation.value.is_not(None)).distinct()
            sets.append(set(self.s.scalars(q)))
        info = None if spec.startswith("=") else self.info(spec)
        formula = spec[1:] if spec.startswith("=") else (info or {}).get("formula") or ""
        if "ultimo(" in formula or "lag(" in formula or "var(" in formula:
            # Funções temporais: a cobertura depende do deslocamento; calcula-se a partir do resultado efetivo.
            df = evaluate(formula, self, level, None, None).df
            return sorted(df.filter(pl.col("value").is_not_null())["period"].unique().to_list())
        return sorted(set.intersection(*sets))

    def _leaf_ids(self, spec: str, depth: int = 0) -> list[str]:
        from .stats.formula import references
        expr = spec[1:] if spec.startswith("=") else spec
        out: list[str] = []
        for r in references(expr):
            info = self.info(r)
            if info is None:
                raise FormulaError(f"Indicador desconhecido: “{r}”.")
            if info["formula"] and depth < 6:
                out += self._leaf_ids(info["formula"], depth + 1)
            else:
                out.append(r)
        return list(dict.fromkeys(out))

    def territories(self, level: str, uf: str | None = None) -> pl.DataFrame:
        q = select(Territory.code, Territory.name, Territory.uf_code, Territory.regiao_code).where(Territory.level == level)
        if uf:
            q = q.where(Territory.uf_code == uf)
        rows = self.s.execute(q).all()
        return pl.DataFrame(rows, schema={"code": pl.String, "name": pl.String, "uf": pl.String, "regiao": pl.String}, orient="row")

    def counts(self) -> dict:
        return dict(
            observations=self.s.scalar(select(func.count()).select_from(Observation).where(Observation.is_current.is_(True))),
            territories=self.s.scalar(select(func.count()).select_from(Territory)),
        )
