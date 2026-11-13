import polars as pl
import pytest

from atlas.stats.formula import FormulaError, UnitT, check_units, evaluate, parse, references, shift_period


def _i(dims, freq="A", formula=None, kind="nominal", sf="fluxo", status="disponivel", percent=False):
    return dict(dims=dims, percent=percent, frequency=freq, formula=formula, value_kind=kind, stock_flow=sf, status=status)


INFO = {
    "pib": _i({"BRL": 1}),
    "pop": _i({"pessoa": 1}, kind="quantidade", sf="estoque"),
    "dep": _i({"BRL": 1}, sf="estoque"),
    "juros": _i({}, freq="M", kind="taxa", sf="na", percent=True),
    "pibpc": _i({"BRL": 1, "pessoa": -1}, formula="pib / pop"),
    "futuro": _i({"BRL": 1}, status="planejado"),
}
DATA = {
    "pib": [("A", "2019", 80.0), ("A", "2020", 100.0), ("B", "2020", 50.0), ("C", "2020", None)],
    "pop": [("A", "2020", 10.0), ("B", "2020", 0.0), ("C", "2020", 5.0), ("D", "2020", 7.0)],
    "dep": [("A", "2020", 40.0), ("B", "2020", 0.0)],
    "juros": [("A", "2020-01", 1.0)],
}


class Fake:
    def info(self, i):
        return INFO.get(i)

    def load(self, i, level, periods, codes):
        rows = [r for r in DATA[i] if periods is None or r[1] in periods]
        return pl.DataFrame(rows, schema={"code": pl.String, "period": pl.String, "value": pl.Float64}, orient="row")

    def deflator(self, freq, stock_flow):
        return {"2019": 2.0, "2020": 1.0}, "2020"


def val(res, code, period="2020"):
    r = res.df.filter((pl.col("code") == code) & (pl.col("period") == period))
    return r["value"][0] if r.height else "sem linha"


def test_divisao_compoe_unidades_e_trata_zero_e_ausente():
    res = evaluate("pib / pop", Fake(), "MUN", ["2020"])
    assert res.unit == UnitT.of({"BRL": 1, "pessoa": -1})
    assert val(res, "A") == 10.0
    assert val(res, "B") is None and res.div_zero == 1  # divisão por zero -> ausente, contada
    assert val(res, "C") is None  # numerador ausente -> ausente (nunca zero)
    assert val(res, "D") is None  # sem numerador -> ausente


def test_soma_exige_mesma_unidade():
    with pytest.raises(FormulaError, match="Unidades incompatíveis"):
        evaluate("pib + pop", Fake(), "MUN")
    assert evaluate("pib + dep", Fake(), "MUN", ["2020"]).unit == UnitT.of({"BRL": 1})


def test_pct_exige_mesma_unidade_e_gera_percentual():
    res = evaluate("pct(dep, pib)", Fake(), "MUN", ["2020"])
    assert res.unit.percent and val(res, "A") == 40.0
    with pytest.raises(FormulaError):
        evaluate("pct(pib, pop)", Fake(), "MUN")


def test_periodicidades_diferentes_nao_sao_combinadas():
    with pytest.raises(FormulaError, match="periodicidades diferentes"):
        evaluate("pib / juros", Fake(), "MUN")


def test_var_lag_e_real():
    assert val(evaluate("var(pib, 1)", Fake(), "MUN", ["2020"]), "A") == pytest.approx(25.0)
    assert val(evaluate("lag(pib, 1)", Fake(), "MUN", ["2020"]), "A") == 80.0
    # real: 2019 vale 80 * 2 = 160 a preços de 2020 -> variação real = 100/160 - 1
    assert val(evaluate("var(real(pib), 1)", Fake(), "MUN", ["2020"]), "A") == pytest.approx(-37.5)
    res = evaluate("real(pib)", Fake(), "MUN", ["2019"])
    assert val(res, "A", "2019") == 160.0 and not res.nominal and res.notes
    with pytest.raises(FormulaError, match="só se aplica a valores em reais"):
        evaluate("real(pop)", Fake(), "MUN")


def test_indicador_derivado_usa_unidade_do_catalogo_e_planejado_e_recusado():
    assert val(evaluate("pibpc * 2", Fake(), "MUN", ["2020"]), "A") == 20.0
    with pytest.raises(FormulaError, match="ainda não possui dados"):
        evaluate("futuro / pop", Fake(), "MUN")
    with pytest.raises(FormulaError, match="desconhecido"):
        evaluate("nao_existe * 2", Fake(), "MUN")


@pytest.mark.parametrize("expr", [
    "__import__('os').system('x')", "pib.__class__", "[1,2]", "pib if pop else 1", "lambda: 1", "open('x')", "pib > 1", "",
])
def test_sintaxe_insegura_ou_invalida_e_rejeitada(expr):
    with pytest.raises(FormulaError):
        parse(expr)


def test_utilitarios():
    assert references("pct(dep, pib) + var(pib, 2)") == ["dep", "pib"]
    assert check_units("pib / pop", Fake()).label() == "R$/habitante"
    assert shift_period("2020", -1) == "2019"
    assert shift_period("2020-01", -1) == "2019-12" and shift_period("2019-12", 2) == "2020-02"
    with pytest.raises(FormulaError):
        evaluate("2 + 2", Fake(), "MUN")


def test_part_trata_participacao_fora_de_0_a_100_como_ausente():
    data = {"parte": [("A", "2020", 30.0), ("B", "2020", -5.0), ("C", "2020", 150.0), ("D", "2020", 0.0)],
            "todo": [("A", "2020", 100.0), ("B", "2020", 100.0), ("C", "2020", 100.0), ("D", "2020", 100.0)]}

    class L(Fake):
        def info(self, i):
            return _i({"BRL": 1}) if i in data else None

        def load(self, i, level, periods, codes):
            return pl.DataFrame(data[i], schema={"code": pl.String, "period": pl.String, "value": pl.Float64}, orient="row")

    res = evaluate("part(parte, todo)", L(), "MUN", ["2020"])
    assert val(res, "A") == 30.0 and val(res, "D") == 0.0
    assert val(res, "B") is None and val(res, "C") is None and res.out_of_range == 2
    assert val(evaluate("pct(parte, todo)", L(), "MUN", ["2020"]), "C") == 150.0  # pct() não filtra
