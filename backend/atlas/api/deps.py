"""Utilidades compartilhadas pelas rotas: acesso a dados com cache e tratamento de erros."""
from __future__ import annotations

from collections import OrderedDict

import polars as pl
from fastapi import Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..data import LEVELS, DataAccess, Variable
from ..db import get_session
from ..models import IngestionRun, Territory
from ..stats.formula import FormulaError

_cache: OrderedDict = OrderedDict()
_CACHE_MAX = 400


class Ctx:
    """Contexto de uma requisição: sessão, acesso a dados e cache invalidado a cada nova carga."""

    def __init__(self, session: Session):
        self.s = session
        self.da = DataAccess(session)
        self.version = session.scalar(select(func.max(IngestionRun.id))) or 0

    def level(self, level: str) -> str:
        level = level.upper()
        if level not in LEVELS:
            raise HTTPException(422, f"Nível territorial inválido: {level}. Opções: {', '.join(LEVELS)}.")
        return level

    def resolve(self, spec: str, level: str, periods: list[str] | None = None, codes: list[str] | None = None,
                real: bool = False) -> Variable:
        key = (self.version, spec, level, tuple(periods) if periods is not None else None, real) if codes is None else None
        if key and key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        try:
            v = self.da.resolve(spec, level, periods, codes, real)
        except FormulaError as e:
            raise HTTPException(422, str(e)) from None
        if key:
            _cache[key] = v
            while len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
        return v

    def periods(self, spec: str, level: str) -> list[str]:
        info = None if spec.startswith("=") else self.da.info(spec)
        if info and info["status"] == "planejado":
            raise HTTPException(422, f"“{info['name']}” está catalogado, mas ainda não possui dados integrados.")
        key = (self.version, "periods", spec, level)
        if key not in _cache:
            try:
                _cache[key] = self.da.periods_of(spec, level)
            except FormulaError as e:
                raise HTTPException(422, str(e)) from None
        return _cache[key]

    def latest(self, spec: str, level: str) -> str | None:
        p = self.periods(spec, level)
        return p[-1] if p else None

    def period_or_latest(self, spec: str, level: str, period: str | None) -> str:
        if period:
            return period
        p = self.latest(spec, level)
        if not p:
            raise HTTPException(404, "Não há dados para este indicador neste nível territorial.")
        return p

    def terr(self, level: str) -> pl.DataFrame:
        key = (self.version, "terr", level)
        if key not in _cache:
            _cache[key] = self.da.territories(level)
        return _cache[key]

    def territory(self, code: str) -> Territory:
        t = self.s.get(Territory, code)
        if not t:
            raise HTTPException(404, f"Território não encontrado: {code}.")
        return t

    def uf_siglas(self) -> dict[str, str]:
        key = (self.version, "ufs")
        if key not in _cache:
            _cache[key] = {t.code: t.sigla for t in self.s.scalars(select(Territory).where(Territory.level == "UF"))}
        return _cache[key]


def ctx(session: Session = Depends(get_session)) -> Ctx:
    return Ctx(session)


def named(c: Ctx, df: pl.DataFrame, level: str, uf: str | None = None) -> pl.DataFrame:
    """Junta nomes e UF a uma tabela (code, value...). Mantém territórios sem valor (ausentes explícitos)."""
    t = c.terr(level)
    if uf and level in ("MUN", "RGI", "RGINT"):  # UFs, regiões e Brasil não têm UF "pai": o recorte é ignorado
        t = t.filter(pl.col("uf") == uf)
    return t.join(df, on="code", how="left")


def split_codes(codes: str) -> list[str]:
    out = [x.strip() for x in codes.split(",") if x.strip()]
    if not out:
        raise HTTPException(422, "Informe ao menos um território.")
    if len(out) > 30:
        raise HTTPException(422, "Selecione no máximo 30 territórios.")
    return out
