"""Gravação de observações com preservação de revisões e registro das cargas."""
from __future__ import annotations

import math
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from .db import session_scope
from .log import ctx, get_logger
from .models import IngestionRun, Observation

log = get_logger("store")


def _now() -> datetime:
    """UTC sem fuso (compatível com SQLite e PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# (territory_code, level, period, value, flag)
Row = tuple[str, str, str, float | None, str | None]


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def save_observations(session: Session, run: IngestionRun, indicator_id: str, rows: Iterable[Row]) -> dict:
    """Insere observações novas; valores alterados viram nova revisão (a anterior é preservada)."""
    obs = Observation.__table__
    existing = {
        (r.territory_code, r.period): (r.id, r.value, r.flag, r.revision)
        for r in session.execute(
            select(obs.c.id, obs.c.territory_code, obs.c.period, obs.c.value, obs.c.flag, obs.c.revision).where(
                obs.c.indicator_id == indicator_id, obs.c.is_current.is_(True)
            )
        )
    }
    new, superseded = [], []
    stats = {"new": 0, "revised": 0, "unchanged": 0}
    seen: set[tuple[str, str]] = set()
    for code, level, period, value, flag in rows:
        key = (code, period)
        if key in seen:
            continue
        seen.add(key)
        if value is not None and (math.isnan(value) or math.isinf(value)):
            value, flag = None, flag or "nd"
        cur = existing.get(key)
        rec = dict(indicator_id=indicator_id, territory_code=code, level=level, period=period,
                   value=value, flag=flag, is_current=True, run_id=run.id)
        if cur is None:
            new.append({**rec, "revision": 0})
            stats["new"] += 1
        elif _same(cur[1], value) and cur[2] == flag:
            stats["unchanged"] += 1
        else:
            superseded.append(cur[0])
            new.append({**rec, "revision": cur[3] + 1})
            stats["revised"] += 1
    for i in range(0, len(superseded), 500):
        session.execute(update(obs).where(obs.c.id.in_(superseded[i:i + 500])).values(is_current=False))
    for i in range(0, len(new), 20000):
        session.execute(insert(obs), new[i:i + 20000])
    run.rows_new += stats["new"]
    run.rows_revised += stats["revised"]
    run.rows_unchanged += stats["unchanged"]
    session.flush()
    log.info("observações gravadas", extra=ctx(indicador=indicator_id, **stats))
    return stats


@contextmanager
def ingestion_run(pipeline: str, dataset_id: str | None = None, **params):
    """Registra início, fim, publicação e erro de cada carga em `ingestion_run`."""
    with session_scope() as s:
        run = IngestionRun(pipeline=pipeline, dataset_id=dataset_id, started_at=_now(), params=params)
        s.add(run)
        s.flush()
        run_id = run.id
    try:
        with session_scope() as s:
            run = s.get(IngestionRun, run_id)
            yield s, run
            run.status = "ok"
            run.finished_at = _now()
        log.info("carga concluída", extra=ctx(pipeline=pipeline))
    except Exception as e:  # registra o erro e propaga
        with session_scope() as s:
            run = s.get(IngestionRun, run_id)
            run.status = "erro"
            run.error = f"{type(e).__name__}: {e}"[:2000]
            run.finished_at = _now()
        log.error("carga falhou", extra=ctx(pipeline=pipeline, erro=str(e)[:300]))
        raise
