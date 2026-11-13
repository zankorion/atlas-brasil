"""Carrega os catálogos YAML (fontes, bases, unidades, metodologias, indicadores) no banco."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from ..models import Dataset, Indicator, Methodology, Source, Unit

HERE = Path(__file__).parent


@lru_cache
def read_catalog() -> dict:
    out: dict = {}
    for name in ("sources", "methodologies", "indicators"):
        out.update(yaml.safe_load((HERE / f"{name}.yaml").read_text(encoding="utf-8")))
    return out


def indicator_specs() -> list[dict]:
    cat = read_catalog()
    defaults = cat.get("defaults", {})
    return [{**defaults, **i} for i in cat["indicators"]]


def seed(session: Session) -> dict:
    cat = read_catalog()
    for s in cat["sources"]:
        session.merge(Source(**s))
    session.flush()
    for d in cat["datasets"]:
        d = dict(d)
        d["source_id"] = d.pop("source")
        session.merge(Dataset(**{"status": "integrado", **d}))
    ids = {d["id"] for d in cat["datasets"]}
    for stale in session.query(Dataset).filter(Dataset.id.notin_(ids)).all():
        if not session.query(Indicator).filter(Indicator.dataset_id == stale.id).count():
            session.delete(stale)  # base removida ou renomeada no catálogo
    for u in cat["units"]:
        session.merge(Unit(**{"percent": False, **u}))
    for m in cat["methodologies"]:
        session.merge(Methodology(**m))
    session.flush()
    for n, i in enumerate(indicator_specs()):
        i = dict(i)
        i.pop("origem", None)
        session.merge(
            Indicator(
                id=i["id"],
                name=i["name"],
                short_name=i.get("short_name"),
                description=i.get("description"),
                dimension=i["dimension"],
                unit_id=i["unit"],
                nature=i["nature"],
                value_kind=i["value_kind"],
                stock_flow=i.get("stock_flow", "na"),
                frequency=i.get("frequency", "A"),
                additive=i.get("additive", False),
                dataset_id=i.get("dataset"),
                methodology_id=i.get("methodology"),
                formula=i.get("formula"),
                levels=i.get("levels", []),
                status=i.get("status", "disponivel"),
                limitations=i.get("limitations"),
                breaks=i.get("breaks", []),
                decimals=i.get("decimals", 2),
                sort=i.get("sort", n),
            )
        )
    return {
        "sources": len(cat["sources"]),
        "datasets": len(cat["datasets"]),
        "indicators": len(cat["indicators"]),
    }
