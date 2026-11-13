"""Dimensão territorial: localidades e malhas do IBGE (as alterações municipais ficam em emancipacoes.py)."""
from __future__ import annotations

import gzip
import json

from ..config import settings
from ..connectors import ibge
from ..connectors.base import SourceUnavailable
from ..log import ctx, get_logger
from ..models import Territory
from ..store import ingestion_run

log = get_logger("territories")

def run(refresh: bool = False) -> None:
    with ingestion_run("territorios", "ibge_localidades") as (s, run_):
        rows = ibge.territory_rows(ibge.fetch_localidades(refresh=refresh))
        for r in rows:
            s.merge(Territory(**r))
        s.flush()
        run_.rows_new = len(rows)
        run_.publication = "API de Localidades do IBGE (divisão territorial vigente)"

        names = {r["code"]: r for r in rows}

    # Malhas (fora da transação: são arquivos, não linhas do banco)
    for level in ibge.MESH_LEVELS:
        try:
            gj = ibge.fetch_mesh(level, refresh=refresh)
        except SourceUnavailable as e:
            log.error("malha indisponível", extra=ctx(nivel=level, erro=str(e)[:200]))
            continue
        for f in gj["features"]:
            code = str(f["properties"].get("codarea"))
            t = names.get(code, {})
            f["id"] = int(code) if code.isdigit() else code
            f["properties"] = {"code": code, "name": t.get("name"), "uf": t.get("uf_code")}
        body = json.dumps(gj, ensure_ascii=False, separators=(",", ":")).encode()
        (settings.geo_dir / f"{level}.geojson.gz").write_bytes(gzip.compress(body, 6))
        log.info("malha gravada", extra=ctx(nivel=level, feicoes=len(gj["features"]), kb=len(body) // 1024))
