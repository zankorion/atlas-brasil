"""SICONFI: extração das contas da DCA nos diferentes planos de contas e regra de ausência."""
from atlas.connectors.siconfi import extract_despesas, extract_funcoes, extract_receitas, position
from atlas.pipelines.siconfi import rows_for

B, D = "Receitas Brutas Realizadas", "Deduções - FUNDEB"


def _r(cod, conta, valor, coluna=B):
    return {"cod_conta": cod, "conta": conta, "coluna": coluna, "valor": valor}


def test_posicao_no_plano_de_contas():
    assert position("RO1.1.0.0.00.0.0") == "1.1" and position("RO1.0.0.0.00.00.00") == "1"
    assert position("DO4.4.00.00.00.00") == "4.4" and position("RO1.7.1.1.51.1.0") == "1.7.1.1.51.1"


def test_receitas_plano_2022_pai_e_filhas_nao_somam_em_dobro():
    items = [
        _r("TotalReceitas", "TOTAL DAS RECEITAS (III) = (I + II)", 1000.0), _r("TotalReceitas", "TOTAL DAS RECEITAS (III) = (I + II)", 100.0, D),
        _r("RO1.0.0.0.00.0.0", "1.0.0.0.00.0.0 - Receitas Correntes", 900.0), _r("RO1.0.0.0.00.0.0", "1.0.0.0.00.0.0 - Receitas Correntes", 100.0, D),
        _r("RO1.1.0.0.00.0.0", "1.1.0.0.00.0.0 - Impostos, Taxas e Contribuições de Melhoria", 300.0),
        _r("RO1.1.1.2.50.0.0", "1.1.1.2.50.0.0 - Imposto sobre a Propriedade Predial e Territorial Urbana", 120.0),
        _r("RO1.1.1.2.50.0.1", "1.1.1.2.50.0.1 - Imposto sobre a Propriedade Predial e Territorial Urbana - Principal", 110.0),
        _r("RO1.1.1.4.51.1.0", "1.1.1.4.51.1.0 - Imposto sobre Serviços de Qualquer Natureza - ISSQN", 150.0),
        _r("RO1.7.0.0.00.0.0", "1.7.0.0.00.0.0 - Transferências Correntes", 500.0), _r("RO1.7.0.0.00.0.0", "1.7.0.0.00.0.0 - Transferências Correntes", 100.0, D),
        _r("RO1.7.1.1.51.0.0", "1.7.1.1.51.0.0 -Cota-Parte do Fundo de Participação dos Municípios - FPM", 200.0),
        _r("RO1.7.1.1.51.0.0", "1.7.1.1.51.0.0 -Cota-Parte do Fundo de Participação dos Municípios - FPM", 40.0, D),
        _r("RO1.7.1.1.51.1.0", "1.7.1.1.51.1.0 - Cota-Parte do Fundo de Participação dos Municípios - Cota Mensal", 180.0),
        _r("RO1.9.1.1.38.0.0", "Multas e Juros de Mora do Imposto sobre a Propriedade Predial", 5.0),  # fora do grupo 1.1: não é IPTU
        _r("RI7.0.0.0.00.0.0", "7.0.0.0.00.0.0 - Receitas Correntes", 77.0),  # intraorçamentária: ignorada
    ]
    r = extract_receitas(items)
    assert r["receita_total"] == 900.0 and r["receita_corrente"] == 800.0  # líquidas das deduções
    assert r["receita_tributaria"] == 300.0 and r["transferencias_correntes"] == 400.0
    assert r["iptu"] == 120.0 and r["iss"] == 150.0  # conta-mãe, sem somar a filha
    assert r["fpm"] == 160.0  # 200 - 40 de dedução; a cota mensal é filha
    assert r["itbi"] is None and r["receita_capital"] is None  # conta ausente: ausente, não zero


def test_receitas_plano_2017_contas_irmas_sao_somadas():
    items = [
        _r("RO1.7.2.1.01.02.00", "1.7.2.1.01.02.00 - Cota-Parte do Fundo de Participação dos Municípios - Cota Mensal", 100.0),
        _r("RO1.7.2.1.01.03.00", "1.7.2.1.01.03.00 - Cota-Parte do Fundo de Participação dos Municípios - 1% Cota entregue em dezembro", 6.0),
        _r("RO1.1.1.2.02.00.00", "1.1.1.2.02.00.00 - Imposto sobre a Propriedade Predial e Territorial Urbana ¿ IPTU", 50.0),
        _r("RO1.1.1.2.02.00.00", "1.1.1.2.02.00.00 - Imposto sobre a Propriedade Predial e Territorial Urbana ¿ IPTU", 4.0, "Outras Deduções da Receita"),
    ]
    r = extract_receitas(items)
    assert r["fpm"] == 106.0 and r["iptu"] == 46.0


def test_despesas_empenhadas_por_natureza_e_funcao():
    E = "Despesas Empenhadas"
    nat = [_r("TotalDespesas", "Total Geral da Despesa", 500.0, E), _r("DO3.0.00.00.00.00", "3.0.00.00.00 - Despesas Correntes", 400.0, E),
           _r("DO3.1.00.00.00.00", "3.1.00.00.00 - Pessoal e Encargos Sociais", 250.0, E), _r("DO3.1.00.00.00.00", "x", 240.0, "Despesas Pagas"),
           _r("DO4.4.00.00.00.00", "4.4.00.00.00 - Investimentos", 60.0, E), _r("DI3.1.91.13.03.00", "Contribuição Patronal - Intra", 9.0, E)]
    d = extract_despesas(nat)
    assert d == dict(despesa_total=500.0, despesa_corrente=400.0, despesa_capital=None, despesa_pessoal=250.0, investimentos=60.0)
    fun = [_r("TotalDespesas", "10 - Saúde", 120.0, E), _r("TotalDespesas", "10.301 - Atenção Básica", 80.0, E),
           _r("TotalDespesas", "12 - Educação", 150.0, E), _r("TotalDespesas", "12 - Educação", 10.0, E)]  # repetição no bloco intra
    assert extract_funcoes(fun) == dict(despesa_saude=120.0, despesa_educacao=150.0)


def test_municipio_sem_declaracao_nao_gera_observacao():
    recs = {
        "A": {"code": "A", "itens": {"receitas": 90, "despesas": 100, "funcoes": 0}, "receita_total": 10.0, "iptu": None, "despesa_saude": None},
        "B": {"code": "B", "itens": {"receitas": 0, "despesas": 0, "funcoes": 0}},
    }
    rows = rows_for(recs, "2023")
    assert rows["fin_receita_total"] == [("A", "MUN", "2023", 10.0, None)]
    assert rows["fin_iptu"] == [("A", "MUN", "2023", None, "nd")] and rows["fin_despesa_saude"] == [("A", "MUN", "2023", None, "nd")]
