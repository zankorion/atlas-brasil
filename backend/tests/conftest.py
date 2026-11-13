"""Banco SQLite temporário e isolado para os testes (nunca toca data/atlas.db)."""
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="atlas_test_")
os.environ["ATLAS_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db".replace("\\", "/")
os.environ["ATLAS_DATA_DIR"] = _tmp

import pytest  # noqa: E402

from atlas.catalog.loader import seed  # noqa: E402
from atlas.db import engine, session_scope  # noqa: E402
from atlas.models import Base, Territory  # noqa: E402
from atlas.store import ingestion_run, save_observations  # noqa: E402


@pytest.fixture(scope="session")
def db():
    """Catálogo real + um punhado de observações SINTÉTICAS, usadas apenas nos testes."""
    Base.metadata.create_all(engine)
    with session_scope() as s:
        seed(s)
        s.add(Territory(code="BR", level="BR", name="Brasil", name_norm="brasil", sigla="BR"))
        s.add(Territory(code="35", level="UF", name="São Paulo", name_norm="sao paulo", sigla="SP", uf_code="35", regiao_code="3"))
        for code, name in (("3500001", "Alfa"), ("3500002", "Beta"), ("3500003", "Gama"), ("3500004", "Delta")):
            s.add(Territory(code=code, level="MUN", name=name, name_norm=name.lower(), uf_code="35", regiao_code="3"))
    with ingestion_run("teste", "atlas_derivados") as (s, run):
        save_observations(s, run, "populacao", [
            ("3500001", "MUN", "2020", 1000.0, None), ("3500002", "MUN", "2020", 2000.0, None),
            ("3500003", "MUN", "2020", 4000.0, None), ("3500004", "MUN", "2020", None, "nd"),
            ("3500001", "MUN", "2021", 1100.0, None), ("3500002", "MUN", "2021", 2000.0, None)])
        save_observations(s, run, "pib_nominal", [
            ("3500001", "MUN", "2020", 10000.0, None), ("3500002", "MUN", "2020", 60000.0, None),
            ("3500003", "MUN", "2020", 80000.0, None), ("3500004", "MUN", "2020", 5000.0, None)])
        save_observations(s, run, "credito_total", [
            ("3500001", "MUN", "2020", 500.0, None), ("3500002", "MUN", "2020", 900.0, None)])
        deps = {"depositos_vista": [("3500001", 250.0), ("3500002", 0.0)], "depositos_poupanca": [("3500001", 250.0), ("3500002", 0.0)],
                "depositos_prazo": [("3500001", 500.0), ("3500002", 0.0)]}
        for k, rows in deps.items():
            save_observations(s, run, k, [(c, "MUN", "2020", v, None) for c, v in rows])
        save_observations(s, run, "ipca_indice", [("BR", "BR", f"{y}-{m:02d}", 100.0 * (2 if y == 2021 else 1), None)
                                                  for y in (2020, 2021) for m in range(1, 13)])
        save_observations(s, run, "selic", [("BR", "BR", "2020-01", 4.5, None)])
    yield


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    from atlas.api.main import app

    return TestClient(app)
