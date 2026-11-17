"""Ipeadata / Atlas do Desenvolvimento Humano: leitura da resposta e regra de ausência."""
import json

from atlas.connectors.ipea import IpeaValue, parse_series
from atlas.pipelines.ipea import rows_for


def test_leitura_da_serie_por_nivel():
    body = json.dumps({"value": [
        {"SERCODIGO": "ADH_IDHM", "VALDATA": "2010-01-01T00:00:00-02:00", "VALVALOR": 0.805, "NIVNOME": "Municípios", "TERCODIGO": "3500001"},
        {"SERCODIGO": "ADH_IDHM", "VALDATA": "2010-01-01T00:00:00-02:00", "VALVALOR": 0.783, "NIVNOME": "Estados", "TERCODIGO": "35"},
        {"SERCODIGO": "ADH_IDHM", "VALDATA": "1991-01-01T00:00:00-02:00", "VALVALOR": 0.493, "NIVNOME": "Brasil", "TERCODIGO": "0"},
        {"SERCODIGO": "ADH_IDHM", "VALDATA": "2010-01-01T00:00:00-02:00", "VALVALOR": None, "NIVNOME": "Municípios", "TERCODIGO": "3500002"},
        {"SERCODIGO": "ADH_IDHM", "VALDATA": "2010-01-01T00:00:00-02:00", "VALVALOR": 0.7, "NIVNOME": "Regiões", "TERCODIGO": "3"},
    ]}).encode()
    got = parse_series(body)
    assert got == [IpeaValue("3500001", "MUN", "2010", 0.805), IpeaValue("35", "UF", "2010", 0.783),
                   IpeaValue("BR", "BR", "1991", 0.493), IpeaValue("3500002", "MUN", "2010", None)]  # nível não usado: ignorado


def test_ausente_nao_vira_zero_e_fora_da_malha_e_ignorado():
    values = [IpeaValue("3500001", "MUN", "2010", 0.8), IpeaValue("3500002", "MUN", "2010", None), IpeaValue("9999999", "MUN", "2010", 0.5)]
    assert rows_for(values, {"3500001", "3500002"}) == [("3500001", "MUN", "2010", 0.8, None), ("3500002", "MUN", "2010", None, "nd")]
