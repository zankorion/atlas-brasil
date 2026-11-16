"""INEP: IDEB, Censo Escolar (microdados por escola) e indicadores educacionais por município.

Todos os arquivos são planilhas ou CSVs compactados publicados em download.inep.gov.br. O arquivo original fica
no cache bruto (`data/raw/inep`); aqui ele é apenas lido — nenhum valor é estimado ou corrigido.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from typing import Iterator

import polars as pl

from .base import NotPublished, _cache_path, fetch

BASE = "https://download.inep.gov.br"
MISSING = {"", "-", "--", "---", "ND", "ND*", "ND**", "*", "**", "***", "NA", "N/A", "X", "None"}


def number(v) -> float | None:
    """Converte uma célula do INEP em número; traço, asterisco e 'ND' são ausência (nunca zero)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in MISSING:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def plain(v) -> str:
    """Texto sem acentos, em minúsculas, para comparar rótulos ('Pública', 'PUBLICA')."""
    s = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def _archive(path: str, refresh: bool = False) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(fetch(f"{BASE}/{path}", namespace="inep", cache_key=path, suffix=".zip", refresh=refresh)))


def _first_archive(paths: list[str], refresh: bool = False) -> tuple[zipfile.ZipFile, str]:
    """O INEP muda o nome do arquivo de um ano para outro: tenta os endereços conhecidos, em ordem."""
    if not refresh:  # o que já foi baixado vale antes de qualquer nova tentativa de rede
        for p in paths:
            if _cache_path("inep", p, ".zip").exists():
                return _archive(p), p
    for p in paths:
        try:
            return _archive(p, refresh), p
        except (NotPublished, zipfile.BadZipFile):
            continue
    raise NotPublished(paths[0])


def sheet_rows(z: zipfile.ZipFile) -> Iterator[tuple]:
    """Linhas de todas as abas da planilha (.xlsx ou .xls) do arquivo compactado."""
    names = [i.filename for i in z.infolist() if not i.is_dir()]
    xlsx = [n for n in names if n.lower().endswith(".xlsx")]
    xls = [n for n in names if n.lower().endswith(".xls")]
    if xlsx:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(z.read(xlsx[0])), read_only=True, data_only=True)
        for ws in wb.worksheets:
            yield from ws.iter_rows(values_only=True)
    elif xls:
        import xlrd

        for sh in xlrd.open_workbook(file_contents=z.read(xls[0])).sheets():  # .xls tem limite de 65 mil linhas por aba
            for i in range(sh.nrows):
                yield tuple(sh.row_values(i))
    else:
        raise NotPublished(f"sem planilha no arquivo: {names[:5]}")


def table(rows: Iterator[tuple], key: str = "CO_MUNICIPIO") -> Iterator[dict]:
    """Registros a partir da linha de nomes de variáveis (a que contém `key`); o cabeçalho descritivo é ignorado."""
    header: list[str] | None = None
    for row in rows:
        if header is None:
            cells = [str(c).strip() if c is not None else "" for c in row]
            if key in cells:
                header = cells
            continue
        if row and row[0] is not None:
            yield {h: v for h, v in zip(header, row) if h}


def mun_code(v) -> str | None:
    s = str(v).strip().split(".")[0] if v is not None else ""
    return s if len(s) == 7 and s.isdigit() else None


# ------------------------------------------------------------------ IDEB
IDEB_FILES = {"anos_iniciais": "anos_iniciais", "anos_finais": "anos_finais", "ensino_medio": "ensino_medio"}
IDEB_EDITION = 2023


def parse_ideb(rows: Iterator[tuple], network: str = "publica") -> dict[tuple[str, str], float | None]:
    """{(município, ano): IDEB} da rede dada. O arquivo de uma edição traz toda a série desde 2005."""
    out: dict[tuple[str, str], float | None] = {}
    for rec in table(rows):
        code = mun_code(rec.get("CO_MUNICIPIO"))
        if not code or plain(rec.get("REDE")) != network:
            continue
        for col, v in rec.items():
            m = re.fullmatch(r"VL_OBSERVADO_(\d{4})", col)
            if m:
                out[(code, m.group(1))] = number(v)
    return out


def fetch_ideb(stage: str, refresh: bool = False) -> dict[tuple[str, str], float | None]:
    z = _archive(f"ideb/resultados/divulgacao_{IDEB_FILES[stage]}_municipios_{IDEB_EDITION}.zip", refresh)
    return parse_ideb(sheet_rows(z))


# ------------------------------------------------------------------ rendimento e distorção idade-série
_IND = "informacoes_estatisticas/indicadores_educacionais"
RATES_FIRST, TDI_FIRST = 2013, 2011


def _rates_paths(y: int) -> list[str]:
    return [f"{_IND}/{y}/tx_rend_municipios_{y}.zip", f"{_IND}/{y}/TX_REND_MUNICIPIOS_{y}.zip", f"{_IND}/{y}/TAXA_REND_{y}_MUNICIPIOS.zip",
            f"{_IND}/{y}/taxa_rendimento/tx_rendimento_municipios_{y}.zip"]


def _tdi_paths(y: int) -> list[str]:
    return [f"{_IND}/{y}/TDI_{y}_MUNICIPIOS.zip", f"{_IND}/{y}/distorcao_idade_serie/tdi_municipios_{y}.zip"]


# As planilhas têm sempre a mesma ordem: 7 colunas de identificação (ano, região, UF, código, nome, localização,
# rede) e blocos de valores. Os nomes de variáveis mudaram (e nem sempre existem), então a leitura é por posição,
# conferida contra o cabeçalho descritivo: cada posição usada precisa ser um "Total" (do fundamental ou do médio).
RATE_COLS = {"aprovacao_fund": 7, "aprovacao_medio": 19, "reprovacao_fund": 25, "reprovacao_medio": 37, "abandono_fund": 43, "abandono_medio": 55}
TDI_COLS = {"distorcao_fund": 7, "distorcao_medio": 19}


class LayoutChanged(RuntimeError):
    """A planilha não tem a disposição de colunas esperada: melhor não carregar do que carregar a coluna errada."""


def parse_totals(rows: Iterator[tuple], cols: dict[str, int]) -> dict[str, dict[str, float | None]]:
    """{município: {campo: valor}} da linha 'Total' (todas as localizações e redes) de cada município."""
    out: dict[str, dict[str, float | None]] = {}
    shift: int | None = None  # 1 quando a planilha traz também a coluna "Código da UF" (ex.: distorção de 2015)
    width = max(cols.values()) + 2
    for row in rows:
        row = tuple(row) + (None,) * (width - len(row))
        if shift is None:
            shift = next((d for d in (0, 1) if all(plain(row[i + d]).startswith("total") for i in cols.values())), None)
            if shift is None and (mun_code(row[3]) or mun_code(row[4])):
                raise LayoutChanged("cabeçalho sem 'Total' nas colunas esperadas")
            continue
        code = mun_code(row[3 + shift])
        if code and plain(row[5 + shift]) == "total" and plain(row[6 + shift]) == "total":
            out[code] = {field: number(row[i + shift]) for field, i in cols.items()}
    if shift is None:
        raise LayoutChanged("cabeçalho sem 'Total' nas colunas esperadas")
    return out


def check_rates(data: dict[str, dict[str, float | None]]) -> None:
    """Aprovação + reprovação + abandono somam 100 em cada etapa: confere que as colunas lidas são as certas."""
    for stage in ("fund", "medio"):
        sums = [sum(r[f"{k}_{stage}"] for k in ("aprovacao", "reprovacao", "abandono")) for r in data.values()
                if all(r[f"{k}_{stage}"] is not None for k in ("aprovacao", "reprovacao", "abandono"))]
        if not sums or sum(1 for x in sums if abs(x - 100) <= 0.3) < 0.98 * len(sums):
            raise LayoutChanged(f"taxas de rendimento ({stage}) não somam 100")


def fetch_rates(year: int, refresh: bool = False) -> dict[str, dict[str, float | None]]:
    z, _ = _first_archive(_rates_paths(year), refresh)
    data = parse_totals(sheet_rows(z), RATE_COLS)
    check_rates(data)
    return data


def fetch_tdi(year: int, refresh: bool = False) -> dict[str, dict[str, float | None]]:
    z, _ = _first_archive(_tdi_paths(year), refresh)
    return parse_totals(sheet_rows(z), TDI_COLS)


# ------------------------------------------------------------------ Censo Escolar (microdados por escola)
CENSUS_FIRST = 2007  # microdados no formato atual; de 1995 a 2006 o questionário e as variáveis são outros
# campo do Atlas -> coluna dos microdados (quantidades por escola)
CENSUS_SUMS = {
    "matriculas": "QT_MAT_BAS", "mat_creche": "QT_MAT_INF_CRE", "mat_pre": "QT_MAT_INF_PRE", "mat_fund_ai": "QT_MAT_FUND_AI",
    "mat_fund_af": "QT_MAT_FUND_AF", "mat_medio": "QT_MAT_MED", "mat_eja": "QT_MAT_EJA", "mat_prof": "QT_MAT_PROF", "turmas": "QT_TUR_BAS",
}
PUBLIC, MUNICIPAL, PRIVATE = ("1", "2", "3"), ("3",), ("4",)  # TP_DEPENDENCIA: 1 federal, 2 estadual, 3 municipal, 4 privada
CENSUS_FIELDS = ["escolas", *CENSUS_SUMS, "mat_publica", "mat_municipal", "mat_privada"]


def aggregate_schools(df: pl.DataFrame) -> pl.DataFrame:
    """Soma as escolas em atividade por município. Coluna que não existe no ano fica ausente (nunca zero)."""
    def num(col: str) -> pl.Expr:
        if col not in df.columns:
            return pl.lit(None, dtype=pl.Float64)
        return pl.col(col).cast(pl.String).str.strip_chars().cast(pl.Float64, strict=False)

    dep = pl.col("TP_DEPENDENCIA").cast(pl.String).str.strip_chars()
    active = df.filter(pl.col("TP_SITUACAO_FUNCIONAMENTO").cast(pl.String).str.strip_chars() == "1")
    base = active.select(
        pl.col("CO_MUNICIPIO").cast(pl.String).str.strip_chars().alias("code"), dep.alias("dep"),
        *[num(c).alias(f) for f, c in CENSUS_SUMS.items()])
    mat = pl.col("matriculas")

    def total(field: str) -> pl.Expr:
        # soma das escolas; se a variável não foi coletada no ano (tudo nulo), o total é ausente
        return pl.when(pl.col(field).is_not_null().any()).then(pl.col(field).sum()).otherwise(None).alias(field)

    out = base.group_by("code").agg(
        pl.len().cast(pl.Float64).alias("escolas"), *[total(f) for f in CENSUS_SUMS],
        mat.filter(pl.col("dep").is_in(PUBLIC)).sum().alias("mat_publica"),
        mat.filter(pl.col("dep").is_in(MUNICIPAL)).sum().alias("mat_municipal"),
        mat.filter(pl.col("dep").is_in(PRIVATE)).sum().alias("mat_privada"))
    collected = {f: base[f].is_not_null().any() for f in CENSUS_SUMS}
    # variável não coletada no ano: ausente em todos os municípios, em vez do zero que a soma de nulos produziria
    return out.with_columns([pl.lit(None, dtype=pl.Float64).alias(f) for f, ok in collected.items() if not ok]
                            + ([pl.lit(None, dtype=pl.Float64).alias(f) for f in ("mat_publica", "mat_municipal", "mat_privada")]
                               if not collected["matriculas"] else []))


def fetch_census(year: int, refresh: bool = False) -> pl.DataFrame:
    z = _archive(f"dados_abertos/microdados_censo_escolar_{year}.zip", refresh)
    names = [i.filename for i in z.infolist() if i.filename.lower().endswith(".csv")]
    main = next((n for n in names if "ed_basica" in n.lower()), None)
    if main is None:
        raise NotPublished(f"microdados da educação básica de {year}: CSV não encontrado")
    raw = z.read(main)
    header = raw[: raw.index(b"\n")].decode("latin-1").strip().split(";")
    want = [c for c in ["CO_MUNICIPIO", "TP_DEPENDENCIA", "TP_SITUACAO_FUNCIONAMENTO", *CENSUS_SUMS.values()] if c in header]
    df = pl.read_csv(io.BytesIO(raw), separator=";", encoding="latin1", columns=want, infer_schema_length=0, quote_char='"',
                     truncate_ragged_lines=True)
    return aggregate_schools(df)
