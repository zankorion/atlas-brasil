"""Linha de comando do Atlas.

    python -m atlas.cli migrate            # aplica as migrações
    python -m atlas.cli seed               # carrega catálogos (fontes, metodologias, indicadores)
    python -m atlas.cli ingest all         # executa todos os pipelines
    python -m atlas.cli ingest sidra --so ibge_pam   # só uma base do SIDRA
    python -m atlas.cli ingest estban --inicio 2020
    python -m atlas.cli status             # resumo do banco e das últimas cargas
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .log import ctx, get_logger

log = get_logger("cli")
BACKEND = Path(__file__).resolve().parents[1]

PIPELINES = ["territorios", "emancipacoes", "sgs", "populacao", "sidra", "domicilios", "censo_agro", "estban",
             "cooperativas", "scr", "agregacao"]


def migrate() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    command.upgrade(cfg, "head")


def seed() -> None:
    from .catalog.loader import seed as _seed
    from .db import session_scope

    with session_scope() as s:
        log.info("catálogo carregado", extra=ctx(**_seed(s)))


def ingest(name: str, args) -> None:
    from .pipelines import aggregate, bcb, cooperativas, emancipacoes, sidra, territories

    refresh = args.refresh
    if name == "territorios":
        territories.run(refresh=refresh)
    elif name == "emancipacoes":
        emancipacoes.run(refresh=refresh)
    elif name == "cooperativas":
        cooperativas.run_postos(start=args.inicio or 2016, end=args.fim, refresh=refresh)
    elif name == "scr":
        cooperativas.run_scr(start=args.inicio or 2012, end=args.fim, refresh=refresh)
    elif name == "sgs":
        bcb.run_sgs()
    elif name == "populacao":
        sidra.run_populacao(refresh=refresh)
    elif name in ("sidra", "pib"):
        sidra.run_catalog(refresh=refresh, only=args.so)
    elif name == "domicilios":
        sidra.run_domicilios(refresh=refresh)
    elif name == "censo_agro":
        sidra.run_censo_agro(refresh=refresh)
    elif name == "estban":
        bcb.run_estban(start=args.inicio, end=args.fim, refresh=refresh)
    elif name == "agregacao":
        aggregate.run()
    else:
        raise SystemExit(f"Pipeline desconhecido: {name}. Opções: {', '.join(PIPELINES)}, all")


def status() -> None:
    from sqlalchemy import func, select

    from .db import session_scope
    from .models import IngestionRun, Observation

    with session_scope() as s:
        print("Observações vigentes por indicador:")
        q = (select(Observation.indicator_id, func.count(), func.min(Observation.period), func.max(Observation.period))
             .where(Observation.is_current.is_(True)).group_by(Observation.indicator_id).order_by(Observation.indicator_id))
        for ind, n, p0, p1 in s.execute(q):
            print(f"  {ind:28s} {n:>9,d}  {p0} – {p1}")
        print("\nÚltimas cargas:")
        for r in s.scalars(select(IngestionRun).order_by(IngestionRun.id.desc()).limit(15)):
            print(f"  #{r.id:<3d} {r.pipeline:12s} {r.status:8s} novas={r.rows_new:<8d} revisadas={r.rows_revised:<6d} "
                  f"{(r.error or r.publication or '')[:90]}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="atlas", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    sub.add_parser("seed")
    sub.add_parser("status")
    pi = sub.add_parser("ingest")
    pi.add_argument("pipeline")
    pi.add_argument("--refresh", action="store_true", help="ignora o cache bruto e baixa novamente da fonte")
    pi.add_argument("--inicio", type=int, default=None)
    pi.add_argument("--so", default=None, help="sidra: carrega só um indicador ou uma base (id)")
    pi.add_argument("--fim", type=int, default=None)
    a = p.parse_args(argv)
    if a.cmd == "migrate":
        migrate()
    elif a.cmd == "seed":
        seed()
    elif a.cmd == "status":
        status()
    elif a.cmd == "ingest":
        failed = []
        for name in (PIPELINES if a.pipeline == "all" else [a.pipeline]):
            try:
                ingest(name, a)
            except Exception as e:  # um pipeline com falha não impede os demais
                failed.append(name)
                log.error("pipeline falhou", extra=ctx(pipeline=name, erro=f"{type(e).__name__}: {e}"[:400]))
        if failed:
            print("Pipelines com falha:", ", ".join(failed), file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
