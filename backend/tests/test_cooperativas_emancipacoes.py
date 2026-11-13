import io
import zipfile

import openpyxl
import pytest

from atlas.connectors.bcb_cadastro import is_cooperativa, parse_postos
from atlas.pipelines.emancipacoes import parse_origins


def _postos_zip(header: list[str], rows: list[list], name: str = "202312POSTOS.xlsx") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["BANCO CENTRAL DO BRASIL"])
    ws.append(["Posição: 31.12.2023"])
    ws.append([])
    ws.append(header)
    for r in rows:
        ws.append(r)
    x = io.BytesIO()
    wb.save(x)
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr(name, x.getvalue())
    return z.getvalue()


def test_postos_leiaute_recente_com_codigo_ibge():
    z = _postos_zip(["CNPJ      ", "NOME INSTITUIÇÃO", "SEGMENTO   ", "MUNICIPIO  ", "UF", "MUNICIPIO IBGE"], [
        ["1", "COOP A", "Cooperativa de Crédito", "ALFA", "SP", "3500001"],
        ["2", "BANCO B", "Banco Múltiplo", "ALFA", "SP", "3500001"],
        ["3", "COOP C", "Cooperativa de Crédito", "BETA", "SP", "x"],
    ])
    m = parse_postos(z, "202312")
    assert m.position == "31.12.2023" and m.has_ibge_code and len(m.rows) == 3
    coop = [p for p in m.rows if is_cooperativa(p.segmento)]
    assert [(p.ibge, p.municipio) for p in coop] == [("3500001", "ALFA"), (None, "BETA")]  # código inválido -> associação por nome


def test_postos_leiaute_antigo_sem_codigo_ibge():
    z = _postos_zip(["CNPJ", "NOME INSTITUIÇÃO", "SEGMENTO", "MUNICÍPIO", "UF"], [["1", "COOP A", "Cooperativa de Crédito", "ALFA", "SP"]])
    m = parse_postos(z, "201512")
    assert not m.has_ibge_code and m.rows[0].ibge is None and m.rows[0].municipio == "ALFA"


def test_postos_leiaute_irreconhecivel_falha():
    with pytest.raises(ValueError, match="nenhuma linha reconhecida"):
        parse_postos(_postos_zip(["A", "B"], [["1", "2"]]), "202312")


def test_segmento_de_cooperativa_exclui_banco_cooperativo():
    assert is_cooperativa("Cooperativa de Crédito")
    assert not is_cooperativa("Bancos Comerciais Cooperativo") and not is_cooperativa("Banco Múltiplo")


def test_origens_no_texto_de_formacao_administrativa():
    assert parse_origins("Elevado à categoria de município com a denominação de X, pela Lei Estadual n.º 1, "
                         "de 01-01-1995, desmembrado de Barreiras. Sede no atual distrito.") == ["Barreiras"]
    assert parse_origins("Elevado à categoria de município, desmembrado dos municípios de Água Clara, Costa Rica e "
                         "Chapadão do Sul. Constituído do distrito sede.") == ["Água Clara", "Costa Rica", "Chapadão do Sul"]
    assert parse_origins("desmembrado do município Bento Gonçalves o distrito Pinto Bandeira.") == ["Bento Gonçalves"]
    assert parse_origins("") == [] and parse_origins("Distrito criado em 1900.") == []
