"""INEP: leitura das planilhas (IDEB, rendimento, distorção) e soma das escolas do Censo Escolar."""
import polars as pl
import pytest

from atlas.connectors import inep
from atlas.models import Territory
from atlas.pipelines.inep import census_rows


def test_numero_trata_tracos_e_nd_como_ausencia():
    assert inep.number("231,42") == 231.42 and inep.number("5.9") == 5.9 and inep.number(4) == 4.0
    for missing in ("-", "--", "ND", "*", "", None):
        assert inep.number(missing) is None  # nunca zero
    assert inep.mun_code("1100015") == "1100015" and inep.mun_code(1100015.0) == "1100015" and inep.mun_code("RO") is None


def test_ideb_usa_a_rede_publica_e_todos_os_anos_do_arquivo():
    rows = [
        ("Ministério da Educação",), ("Sigla da UF", "Código do Município", "Nome", "Rede", "IDEB 2021", "IDEB 2023"),
        ("SG_UF", "CO_MUNICIPIO", "NO_MUNICIPIO", "REDE", "VL_OBSERVADO_2021", "VL_OBSERVADO_2023", "VL_PROJECAO_2021"),
        ("SP", "3500001", "Alfa", "Estadual", "4.0", "4.1", "9.9"),
        ("SP", "3500001", "Alfa", "Pública", "5,2", "-", "9.9"),
        ("SP", "3500002", "Beta", "Pública", "ND", "6.1", "9.9"),
        ("Fonte: INEP", None, None, None, None, None, None),
    ]
    got = inep.parse_ideb(iter(rows))
    assert got == {("3500001", "2021"): 5.2, ("3500001", "2023"): None, ("3500002", "2021"): None, ("3500002", "2023"): 6.1}


def _rates_row(code, loc, dep, values: dict[int, object], shift=0):
    row = [None] * (57 + shift)
    row[0], row[3 + shift], row[5 + shift], row[6 + shift] = "2023", code, loc, dep
    for i, v in values.items():
        row[i + shift] = v
    return tuple(row)


def _header(cols, shift=0):
    row = [None] * (57 + shift)
    for i in cols:
        row[i + shift] = "Total  "
    return tuple(row)


def test_rendimento_le_a_linha_total_e_confere_a_soma():
    cols = list(inep.RATE_COLS.values())
    ok = {7: "90.0", 19: "80", 25: "8", 37: "15.5", 43: "2", 55: "4.5"}
    rows = [("Ministério",), _header(cols), _rates_row("3500001", "Total", "Total", ok), _rates_row("3500001", "Urbana", "Total", {7: "1"}),
            _rates_row("3500001", "Total", "Estadual", {7: "1"}), _rates_row("3500002", "Total", "Total", {**ok, 19: "--", 37: "--", 55: "--"})]
    got = inep.parse_totals(iter(rows), inep.RATE_COLS)
    assert got["3500001"] == dict(aprovacao_fund=90.0, aprovacao_medio=80.0, reprovacao_fund=8.0, reprovacao_medio=15.5,
                                  abandono_fund=2.0, abandono_medio=4.5)
    assert got["3500002"]["aprovacao_medio"] is None and got["3500002"]["aprovacao_fund"] == 90.0  # sem ensino médio: ausente
    inep.check_rates(got)
    with pytest.raises(inep.LayoutChanged):  # colunas trocadas não somam 100: melhor não carregar
        inep.check_rates({"X": dict(aprovacao_fund=90.0, reprovacao_fund=90.0, abandono_fund=2.0, aprovacao_medio=80.0,
                                    reprovacao_medio=15.5, abandono_medio=4.5)})


def test_planilha_com_coluna_a_mais_ou_sem_cabecalho_esperado():
    cols = list(inep.TDI_COLS.values())
    shifted = [_header(cols, shift=1), _rates_row("3500001", "Total", "Total", {7: "12.5", 19: "30"}, shift=1)]
    assert inep.parse_totals(iter(shifted), inep.TDI_COLS) == {"3500001": dict(distorcao_fund=12.5, distorcao_medio=30.0)}
    with pytest.raises(inep.LayoutChanged):
        inep.parse_totals(iter([("Ano", "Região"), _rates_row("3500001", "Total", "Total", {7: "1"})]), inep.TDI_COLS)


def _schools():
    return pl.DataFrame({
        "CO_MUNICIPIO": ["3500001", "3500001", "3500001", "3500002", "9999999"],
        "TP_DEPENDENCIA": ["3", "4", "2", "3", "3"],
        "TP_SITUACAO_FUNCIONAMENTO": ["1", "1", "2", "1", "1"],  # a terceira escola está paralisada
        "QT_MAT_BAS": ["100", "40", "999", "10", "5"], "QT_MAT_INF_CRE": ["30", "0", "9", "0", "0"],
        "QT_MAT_MED": ["0", "40", "9", "0", "0"], "QT_TUR_BAS": ["5", "2", "9", "1", "1"],
    })


def test_censo_escolar_soma_escolas_em_atividade_por_rede():
    df = inep.aggregate_schools(_schools()).sort("code")
    a = df.row(0, named=True)
    assert a["code"] == "3500001" and a["escolas"] == 2 and a["matriculas"] == 140 and a["turmas"] == 7
    assert a["mat_municipal"] == 100 and a["mat_publica"] == 100 and a["mat_privada"] == 40 and a["mat_medio"] == 40
    b = df.row(1, named=True)
    assert b["mat_creche"] == 0 and b["mat_privada"] == 0  # há escola e não há matrícula: zero de verdade
    assert a["mat_eja"] is None and a["mat_pre"] is None  # variável que não existe no arquivo do ano: ausente


def test_censo_escolar_agrega_niveis_e_ignora_fora_da_malha():
    terr = {c: Territory(code=c, level="MUN", name=c, name_norm=c, uf_code="35", regiao_code="3", rgi_code="350001", rgint_code="3501")
            for c in ("3500001", "3500002")}
    rows, unknown = census_rows(inep.aggregate_schools(_schools()), terr, "2023")
    assert unknown == 1
    got = {(r[1], r[0]): (r[3], r[4]) for r in rows["esc_matriculas"]}
    assert got[("MUN", "3500001")] == (140.0, None) and got[("MUN", "3500002")] == (10.0, None)
    assert got[("UF", "35")] == (150.0, "agg") and got[("BR", "BR")] == (150.0, "agg") and got[("RGI", "350001")] == (150.0, "agg")
    eja = {(r[1], r[0]): (r[3], r[4]) for r in rows["esc_mat_eja"]}
    assert eja[("MUN", "3500001")] == (None, "nd") and ("BR", "BR") not in eja  # ausente não vira total zero
