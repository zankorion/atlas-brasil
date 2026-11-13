"""API do Atlas Econômico e Social do Brasil (FastAPI).

Executar:  uvicorn atlas.api.main:app --reload --port 8000
Documentação interativa (OpenAPI): http://localhost:8000/docs
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from ..config import settings
from ..db import SessionLocal
from ..log import ctx as logctx
from ..log import get_logger
from . import catalog, data_routes, lab

log = get_logger("api")


def _warm_up() -> None:
    """Pré-calcula, em segundo plano, os quadros que o primeiro perfil de cada nível precisaria montar.

    Sem isso, o primeiro perfil municipal após iniciar a API (ou após uma nova carga) leva vários segundos.
    Falhas aqui não afetam o serviço: o cálculo apenas volta a acontecer sob demanda.
    """
    from .deps import Ctx

    session = SessionLocal()
    try:
        c = Ctx(session)
        for code in ("3550308", "35", "BR"):
            if session.get(catalog.Territory, code):
                data_routes.profile(code, c)
        catalog.indicators(c)
        log.info("cache aquecido", extra=logctx(versao=c.version))
    except Exception as e:  # pragma: no cover - melhor esforço
        log.warning("aquecimento do cache falhou", extra=logctx(erro=str(e)[:200]))
    finally:
        session.close()


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=_warm_up, name="atlas-warmup", daemon=True).start()
    yield


app = FastAPI(
    title="Atlas Econômico e Social do Brasil — API",
    version="0.1.0",
    description="Dados públicos brasileiros padronizados, com fonte, período, unidade e metodologia rastreáveis. "
                "Valores ausentes são nulos — nunca zero.",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)
app.include_router(catalog.router, tags=["catálogo"])
app.include_router(data_routes.router, tags=["dados"])
app.include_router(lab.router, tags=["laboratório"])
