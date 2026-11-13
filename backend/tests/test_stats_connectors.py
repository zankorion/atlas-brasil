import io
import zipfile

import pytest

from atlas.connectors.bcb import parse_estban
from atlas.connectors.ibge import normalize, parse_value
from atlas.stats import core


def test_gini():
    assert core.gini([5, 5, 5, 5]) == pytest.approx(0.0)
    assert core.gini([0, 0, 0, 10]) == pytest.approx(0.75)
    assert core.gini([1, 3], weights=[3, 1]) == pytest.approx(0.25)
    assert core.gini([1]) is None


def test_gini_agrupado():
    assert core.gini_grouped([10, 10, 10], [10, 10, 10]) == pytest.approx(0.0)
    g = core.gini_grouped([90, 9, 1], [90, 90, 820])
    assert 0.7 < g < 1
    assert core.gini_grouped([5, 0, 0], [10, 0, 0]) is None  # menos de 3 classes com unidades


def test_correlacao_e_regressao():
    x, y = [1, 2, 3, 4, 5], [3, 5, 7, 9, 11]
    c = core.correlation(x, y)
    assert c["n"] == 5 and c["pearson"]["r"] == pytest.approx(1) and c["spearman"]["rho"] == pytest.approx(1)
    r = core.ols(x, y)
    assert r["slope"] == pytest.approx(2) and r["intercept"] == pytest.approx(1) and r["r2"] == pytest.approx(1)
    assert core.correlation([1, 1, 1], [1, 2, 3])["pearson"] is None  # variável constante
    assert core.ols([1, 2], [1, 2]) is None  # amostra insuficiente


def test_classificacao():
    assert core.classify(list(range(1, 101)), "quantis", 4) == pytest.approx([25.75, 50.5, 75.25])
    assert core.classify([0, 10], "iguais", 5) == pytest.approx([2, 4, 6, 8])
    empates = core.classify([1, 1, 1, 1, 9], "quantis", 5)
    assert empates == sorted(set(empates))  # limites repetidos são removidos
    assert core.classify([], "quantis", 5) == []


def test_quebras_naturais_separam_os_agrupamentos():
    assert core.classify([1, 2, 3, 10, 11, 12, 50, 51, 52], "jenks", 3) == [3.0, 12.0]
    # um valor muito discrepante fica sozinho na última classe (o que os quantis não fazem)
    assert core.classify([1, 2, 3, 4, 5, 6, 7, 8, 9, 1000], "jenks", 2) == [9.0]
    assert core.classify([1, 1, 1, 1], "jenks", 3) == [] and core.classify([5], "jenks", 3) == []
    grande = core.classify(list(range(5000)), "jenks", 5)  # acima do limite: amostragem por quantis
    assert len(grande) == 4 and grande == sorted(grande)


def test_simbolos_do_sidra_nao_viram_zero():
    assert parse_value("123.5") == (123.5, None)
    assert parse_value("-") == (0.0, None)  # zero absoluto, convenção do IBGE
    assert parse_value("...") == (None, "nd")
    assert parse_value("X") == (None, "sigilo")
    assert parse_value("..") == (None, "na")
    assert normalize("São José d'Oeste") == "sao jose d oeste"


def _estban_zip(header: str, rows: list[str]) -> bytes:
    body = "ESTBAN (Documento 4500) por municipio\nData de geracao dos dados: 2024-08-01\n" + header + "\n" + "\n".join(rows) + "\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("202312_ESTBAN.CSV", body.encode("latin-1"))
    return buf.getvalue()


HEADER = ";".join([
    "#DATA_BASE", "UF", "CODMUN", "MUNICIPIO", "CNPJ", "NOME_INSTITUICAO", "AGEN_ESPERADAS", "AGEN_PROCESSADAS",
    "VERBETE_160_OPERACOES_DE_CREDITO", "VERBETE_161_EMPRES_E_TIT_DESCONTADOS", "VERBETE_162_FINANCIAMENTOS",
    "VERBETE_163_FIN_RURAIS_AGRICUL_CUST/INVEST", "VERBETE_164_FIN_RURAIS_PECUAR_CUST/INVEST",
    "VERBETE_169_FINANCIAMENTOS_IMOBILIARIOS", "VERBETE_401_SERVICOS_PUBLICOS + VERBETE_402_ATIVIDADES_EMPRESARIAIS",
    "VERBETE_420_DEPOSITOS_DE_POUPANCA", "VERBETE_432_DEPOSITOS_A_PRAZO", "CODMUN_IBGE",
])


def test_estban_soma_instituicoes_por_municipio():
    z = _estban_zip(HEADER, [
        "202312;SP;1;ALFA;001;BANCO A;2;2;100;40;30;10;5;15;7;8;9;3500001",
        "202312;SP;1;ALFA;002;BANCO B;1;1;50;;;;;;;;1;3500001",
        "202312;SP;2;SEM CODIGO;003;BANCO C;1;1;999;0;0;0;0;0;0;0;0;",
    ])
    m = parse_estban(z, "202312")
    assert m.generated == "2024-08-01" and m.unmatched_rows == 1 and list(m.municipalities) == ["3500001"]
    a = m.municipalities["3500001"]
    assert a["credito_total"] == 150 and a["agencias"] == 3 and a["credito_rural"] == 15  # verbetes 163 + 164
    assert a["depositos_vista"] == 7 and a["depositos_poupanca"] == 8 and a["depositos_prazo"] == 10


def test_estban_leiaute_inesperado_falha_explicitamente():
    with pytest.raises(ValueError, match="Leiaute ESTBAN inesperado"):
        parse_estban(_estban_zip("#DATA_BASE;UF;CODMUN_IBGE;AGEN_PROCESSADAS;OUTRA", ["202312;SP;3500001;1;5"]), "202312")
