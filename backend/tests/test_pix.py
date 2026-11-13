"""Pix por município: leitura da resposta do BCB e soma anual sem somas parciais."""
import json

from atlas.connectors.bcb_pix import PixRow, parse_month
from atlas.pipelines.pix import annual


def test_parse_month_preserva_ausentes():
    body = json.dumps({"value": [
        {"Municipio_Ibge": 3500001, "VL_PagadorPF": 10.5, "QT_PagadorPF": 2, "VL_PagadorPJ": None, "QT_PagadorPJ": 1,
         "VL_RecebedorPF": 3, "VL_RecebedorPJ": 4, "QT_PES_PagadorPF": 7},
        {"Municipio_Ibge": None, "VL_PagadorPF": 1},
    ]}).encode()
    rows = parse_month(body)
    assert len(rows) == 1 and rows[0].ibge == "3500001"
    assert rows[0].valor_pago_pf == 10.5 and rows[0].valor_pago_pj is None  # nulo não vira zero


def _row(code, v=1.0, pj=1.0, pessoas=5.0):
    return PixRow(code, v, pj, 1.0, 1.0, v, pj, pessoas)


def test_soma_anual_exige_doze_meses():
    months = [[_row("A"), _row("B")] for _ in range(11)] + [[_row("A", pessoas=9.0), _row("Z")]]  # B falta em dezembro; Z fora da malha
    flows, totals, users, info = annual(months, {"A", "B"})
    assert flows["pix_valor"]["A"] == 24.0 and flows["pix_transacoes"]["A"] == 24.0 and flows["pix_valor_pf"]["A"] == 12.0
    assert flows["pix_valor"]["B"] is None  # 11 meses: ausente, nunca soma parcial
    assert totals["pix_valor"]["B"] == 22.0  # mas os 11 meses entram no total da região
    assert users == {"A": 9.0}  # contagem de dezembro
    assert info["incompletos"] == 1 and info["codigos_desconhecidos"] == 1 and info["valor_fora_da_malha"] == 2.0


def test_parcela_ausente_invalida_o_mes():
    months = [[_row("A")] for _ in range(11)] + [[_row("A", pj=None)]]
    flows, _, _, _ = annual(months, {"A"})
    assert flows["pix_valor"]["A"] is None and flows["pix_valor_pf"]["A"] == 12.0
