"""Pipeline genérico do SIDRA: várias origens por indicador, soma de categorias e ausências."""
from sqlalchemy import select

from atlas.connectors.ibge import SidraCell
from atlas.db import session_scope
from atlas.models import Observation
from atlas.pipelines import sidra


def _obs(indicator):
    with session_scope() as s:
        rows = s.execute(select(Observation.territory_code, Observation.period, Observation.value, Observation.flag).where(
            Observation.indicator_id == indicator, Observation.is_current.is_(True))).all()
    return {(r[0], r[1]): (r[2], r[3]) for r in rows}


def test_origens_multiplas_soma_e_ausencias(db, monkeypatch):
    calls = []

    def fake_fetch(table, variable, periods, *, levels, classification=None, refresh=False):
        calls.append((table, variable, tuple(periods), classification))
        if table == "T1":  # duas categorias por município, para somar
            yield SidraCell("3500001", "MUN", "2010", 10.0, None, {"86": "a"})
            yield SidraCell("3500001", "MUN", "2010", 5.0, None, {"86": "b"})
            yield SidraCell("3500002", "MUN", "2010", 7.0, None, {"86": "a"})
            yield SidraCell("3500002", "MUN", "2010", None, "sigilo", {"86": "b"})  # parcela suprimida -> soma ausente
            yield SidraCell("9999999", "MUN", "2010", 1.0, None, {"86": "a"})  # território fora da malha: ignorado
        else:  # segunda origem cobre outro período
            yield SidraCell("3500001", "MUN", "2022", 3.0, None, {})

    spec = dict(id="pop_negra", dataset="ibge_censo_2022", levels=["MUN"], origem=[
        dict(tipo="sidra", tabela="T1", variavel="93", classificacao="86[a,b]", soma=True, periodos=["2010"], escala=2),
        dict(tipo="sidra", tabela="T2", variavel="93", periodos=["2022"], lote=1),
    ])
    monkeypatch.setattr(sidra, "indicator_specs", lambda: [spec])
    monkeypatch.setattr(sidra.ibge, "fetch_sidra", fake_fetch)
    monkeypatch.setattr(sidra.ibge, "sidra_publication", lambda t: f"SIDRA {t}")
    sidra.run_catalog(only="pop_negra")

    got = _obs("pop_negra")
    assert got[("3500001", "2010")] == (30.0, None)  # (10 + 5) x escala 2
    assert got[("3500002", "2010")] == (None, "sigilo")  # nunca soma parcial
    assert got[("3500001", "2022")] == (3.0, None)
    assert ("9999999", "2010") not in got
    assert calls == [("T1", "93", ("2010",), "86[a,b]"), ("T2", "93", ("2022",), None)]
