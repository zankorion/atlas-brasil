from sqlalchemy import select

from atlas.db import session_scope
from atlas.models import Observation
from atlas.store import ingestion_run, save_observations


def test_ausente_nao_e_zero_no_mapa(client):
    j = client.get("/api/map?var=pib_per_capita&level=MUN&period=2020").json()
    vals = {v["code"]: v["value"] for v in j["values"]}
    assert vals["3500001"] == 10.0 and vals["3500002"] == 30.0
    assert vals["3500004"] is None  # população ausente -> per capita ausente
    assert j["n_missing"] == 1 and j["stats"]["n"] == 3
    assert j["meta"]["nature"] == "derivado" and j["meta"]["sources"]


def test_icr_divisao_por_zero_vira_ausente(client):
    j = client.get("/api/map?var=icr&level=MUN&period=2020").json()
    vals = {v["code"]: v["value"] for v in j["values"]}
    assert vals["3500001"] == 50.0  # 500 / (250 + 250 + 500) * 100
    assert vals["3500002"] is None and j["meta"]["div_zero"] == 1
    assert vals["3500003"] is None  # município fora do ESTBAN


def test_deflacionamento_informa_base(client):
    j = client.get("/api/map?var=pib_nominal&level=MUN&period=2020&real=true").json()
    assert j["meta"]["real"] and "IPCA" in j["meta"]["notes"][0]
    assert {v["code"]: v["value"] for v in j["values"]}["3500001"] == 20000.0  # índice dobra entre 2020 e 2021
    j = client.get("/api/map?var=populacao&level=MUN&period=2020&real=true").json()
    assert not j["meta"]["real"] and "não aplicado" in j["meta"]["notes"][0]


def test_formula_validacao(client):
    ok = client.post("/api/lab/formula", json={"expr": "credito_total / populacao", "level": "MUN"}).json()
    assert ok["valid"] and ok["unit"] == "R$/habitante" and ok["periods"] == ["2020"]
    bad = client.post("/api/lab/formula", json={"expr": "pib_nominal + populacao"}).json()
    assert not bad["valid"] and "Unidades incompatíveis" in bad["error"]
    mix = client.post("/api/lab/formula", json={"expr": "pib_nominal * selic", "level": "BR"}).json()
    assert not mix["valid"] and "periodicidades" in mix["error"]
    plan = client.get("/api/map?var=irpf_bens_direitos&level=MUN")
    assert plan.status_code == 422 and "ainda não possui dados" in plan.json()["detail"]


def test_dispersao_informa_amostra_e_ausentes(client):
    j = client.post("/api/lab/scatter", json={"x": "populacao", "y": "pib_nominal", "level": "MUN", "period": "2020"}).json()
    assert j["sample"]["n"] == 3 and j["sample"]["missing_x"] == 1
    assert j["correlation"]["n"] == 3 and "causalidade" in j["warning"]


def test_pesquisa_avancada_conta_nao_avaliados(client):
    j = client.post("/api/lab/search", json={"level": "MUN", "conditions": [
        {"var": "populacao", "op": ">=", "value": 2000, "period": "2020"},
        {"var": "pib_nominal", "op": ">", "ref": "mediana", "period": "2020"}]}).json()
    assert sorted(r["code"] for r in j["rows"]) == ["3500002", "3500003"] and j["n_excluded_missing"] == 1


def test_exportacao_traz_metadados(client):
    text = client.get("/api/export?vars=pib_per_capita&level=MUN&periods=2020&format=csv").text
    assert "fontes:" in text and "formula: pib_nominal / populacao" in text and "não equivalem a zero" in text
    assert "3500004,Delta,SP,MUN,2020,," in text  # ausente exportado vazio
    j = client.get("/api/export?vars=pib_per_capita&level=MUN&periods=2020&format=json").json()
    assert j["metadados"][0]["indicador_id"] == "pib_per_capita" and any(d["valor"] is None for d in j["dados"])
    x = client.get("/api/export?vars=pib_per_capita&level=MUN&periods=2020&format=xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_revisoes_sao_preservadas(db):
    with ingestion_run("teste_revisao", "atlas_derivados") as (s, run):
        st = save_observations(s, run, "vab_total", [("3500003", "MUN", "2020", 80000.0, None)])
    assert st == {"new": 1, "revised": 0, "unchanged": 0}
    with ingestion_run("teste_revisao", "atlas_derivados") as (s, run):
        st = save_observations(s, run, "vab_total", [("3500003", "MUN", "2020", 81000.0, None)])
    assert st == {"new": 0, "revised": 1, "unchanged": 0}
    with session_scope() as s:
        rows = s.execute(select(Observation.value, Observation.revision, Observation.is_current).where(
            Observation.indicator_id == "vab_total", Observation.territory_code == "3500003").order_by(Observation.revision)).all()
    assert [tuple(r) for r in rows] == [(80000.0, 0, False), (81000.0, 1, True)]


def test_catalogo_todas_as_formulas_tem_unidade_coerente(db):
    """Toda fórmula do catálogo deve produzir exatamente as dimensões da unidade declarada."""
    from atlas.catalog.loader import indicator_specs
    from atlas.data import DataAccess
    from atlas.stats.formula import UnitT, check_units

    with session_scope() as s:
        da = DataAccess(s)
        for spec in indicator_specs():
            if spec.get("formula"):
                declared = da.info(spec["id"])
                assert check_units(spec["formula"], da).dims == UnitT.of(declared["dims"]).dims, spec["id"]


def test_recorte_por_uf_e_ignorado_em_niveis_sem_uf(db):
    import polars as pl

    from atlas.api.deps import Ctx, named

    empty = pl.DataFrame(schema={"code": pl.String, "value": pl.Float64})
    with session_scope() as s:
        c = Ctx(s)
        assert named(c, empty, "UF", "99").height == 1  # UFs não têm UF "pai": o recorte é ignorado
        assert named(c, empty, "MUN", "99").height == 0 and named(c, empty, "MUN", "35").height == 4
