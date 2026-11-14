"""Conversão de valores nominais para dólares e gramas de ouro: regra de fluxo/estoque, ausências e unidades."""
import polars as pl
import pytest

from atlas.connectors.worldbank import parse_gold
from atlas.data import money_mode
from atlas.stats.formula import FormulaError, evaluate


class Loader:
    """Dublê: um fluxo e um estoque nominais em reais e uma quantidade."""

    INFO = {
        "fluxo": dict(dims={"BRL": 1}, percent=False, stock_flow="fluxo", value_kind="nominal", frequency="A", formula=None, status="disponivel", levels=["UF"]),
        "estoque": dict(dims={"BRL": 1}, percent=False, stock_flow="estoque", value_kind="nominal", frequency="A", formula=None, status="disponivel", levels=["UF"]),
        "gente": dict(dims={"pessoa": 1}, percent=False, stock_flow="estoque", value_kind="quantidade", frequency="A", formula=None, status="disponivel", levels=["UF"]),
    }

    def __init__(self):
        self.asked = []

    def info(self, i):
        return {"id": i, "name": i, **self.INFO[i]} if i in self.INFO else None

    def load(self, i, level, periods, codes):
        rows = [("35", "2020", 100.0), ("35", "2021", 200.0), ("35", "2022", 300.0)]
        return pl.DataFrame(rows, schema={"code": pl.String, "period": pl.String, "value": pl.Float64}, orient="row")

    def deflator(self, *_):
        return {"2020": 2.0, "2021": 1.5, "2022": 1.0}, "2022"

    def converter(self, kind, freq, stock_flow):
        self.asked.append((kind, freq, stock_flow))
        # 2022 sem cotação (ano incompleto): deve ficar ausente
        return ({"2020": 0.25, "2021": 0.2} if kind == "usd" else {"2020": 0.004, "2021": 0.003}), f"nota {kind}"


def _vals(res):
    return dict(zip(res.df["period"].to_list(), res.df["value"].to_list()))


def test_usd_converte_pela_cotacao_do_periodo_e_deixa_ausente_sem_cotacao():
    ld = Loader()
    r = evaluate("usd(fluxo)", ld, "UF")
    assert _vals(r) == {"2020": 25.0, "2021": 40.0, "2022": None}  # sem cotação: ausente, nunca a de outro ano
    assert dict(r.unit.dims) == {"USD": 1} and not r.nominal and "nota usd" in r.notes
    assert ld.asked == [("usd", "A", "fluxo")]


def test_estoque_pede_a_cotacao_de_estoque_e_ouro_muda_a_unidade():
    ld = Loader()
    r = evaluate("ouro(estoque) / gente", ld, "UF")
    assert ld.asked == [("ouro", "A", "estoque")]
    assert dict(r.unit.dims) == {"g_ouro": 1, "pessoa": -1} and r.unit.label() == "g de ouro/habitante"


def test_conversao_exige_valor_nominal_em_reais():
    ld = Loader()
    with pytest.raises(FormulaError, match="só se aplica a valores em reais"):
        evaluate("usd(gente)", ld, "UF")
    with pytest.raises(FormulaError, match="já foi deflacionada ou convertida"):
        evaluate("usd(real(fluxo))", ld, "UF")  # não se combina com o deflacionamento
    with pytest.raises(FormulaError, match="só se aplica a valores em reais"):
        evaluate("real(ouro(fluxo))", ld, "UF")


def test_opcao_de_valores_monetarios():
    assert [money_mode(x) for x in (False, "", "false", None)] == ["", "", "", ""]
    assert [money_mode(x) for x in (True, "true", "1", "ipca")] == ["ipca"] * 4
    assert money_mode("USD") == "usd" and money_mode("ouro") == "ouro"
    with pytest.raises(FormulaError):
        money_mode("euro")


def test_planilha_do_banco_mundial():
    import io
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Monthly Prices"
    for row in (["World Bank Commodity Price Data"], ["Updated on January 03, 2025"], [], [None, "Crude oil, average", "Gold"],
                [None, "($/bbl)", "($/troy oz)"], ["2024M11", 70.0, 2651.13], ["2024M12", 72.0, 2648.01], ["2025M01", 75.0, "…"]):
        ws.append(row)
    x = io.BytesIO()
    wb.save(x)
    serie, updated = parse_gold(x.getvalue())
    assert serie == [("2024-11", 2651.13), ("2024-12", 2648.01)]  # mês sem preço publicado não entra
    assert updated.startswith("Updated on January")
