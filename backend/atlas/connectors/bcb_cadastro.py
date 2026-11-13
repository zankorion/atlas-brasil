"""Conectores do Banco Central para cooperativas de crédito.

1. Cadastro de postos de atendimento (mensal, planilha compactada):
   https://www.bcb.gov.br/fis/info/agencias.asp
2. SCR.data — carteira de crédito por UF do tomador e tipo de instituição (arquivo anual com um CSV por mês):
   https://www.bcb.gov.br/estabilidadefinanceira/scrdata
"""
from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib
from dataclasses import dataclass, field

import polars as pl

from ..config import settings
from ..log import ctx, get_logger
from .base import NotPublished, SourceUnavailable, client, fetch

log = get_logger("bcb.cadastro")

POSTOS_URL = "https://www.bcb.gov.br/content/estabilidadefinanceira/agenciasconsorcio/postos/{period}POSTOS.zip"
SCR_URL = "https://www.bcb.gov.br/pda/desig/planilha_{year}.zip"


# ------------------------------------------------------------------ postos de atendimento
@dataclass
class Posto:
    segmento: str
    ibge: str | None
    municipio: str
    uf: str


@dataclass
class PostosMonth:
    period: str
    position: str | None
    has_ibge_code: bool
    rows: list[Posto] = field(default_factory=list)


def _sheets(content: bytes, name: str):
    """Itera as linhas (tuplas) de cada planilha de um .xls ou .xlsx."""
    if name.lower().endswith(".xlsx"):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
        for ws in wb.worksheets:
            yield ws.iter_rows(values_only=True)
    else:
        import xlrd

        wb = xlrd.open_workbook(file_contents=content)
        for sh in wb.sheets():
            yield (sh.row_values(i) for i in range(sh.nrows))


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def parse_postos(content: bytes, period: str) -> PostosMonth:
    """Lê o cadastro de postos. O leiaute mudou ao longo do tempo: o código IBGE só existe nos arquivos recentes."""
    z = zipfile.ZipFile(io.BytesIO(content))
    name = z.namelist()[0]
    out = PostosMonth(period=period, position=None, has_ibge_code=False)
    for rows in _sheets(z.read(name), name):
        cols: dict[str, int] | None = None
        for r in rows:
            first = _txt(r[0]) if r else ""
            if cols is None:
                if first.lower().startswith("posição"):
                    out.position = first.split(":", 1)[-1].strip()
                if first.upper() == "CNPJ":
                    cols = {_txt(c).upper().replace("Í", "I"): i for i, c in enumerate(r)}
                continue
            i_seg, i_mun, i_uf = cols.get("SEGMENTO"), cols.get("MUNICIPIO"), cols.get("UF")
            if i_seg is None or i_mun is None or i_uf is None:
                break  # planilha sem as colunas esperadas
            seg = _txt(r[i_seg]) if len(r) > i_seg else ""
            if not seg:
                continue
            i_ibge = cols.get("MUNICIPIO IBGE")
            ibge = _txt(r[i_ibge]) if i_ibge is not None and len(r) > i_ibge else ""
            if i_ibge is not None:
                out.has_ibge_code = True
            out.rows.append(Posto(seg, ibge if ibge.isdigit() and len(ibge) == 7 else None, _txt(r[i_mun]), _txt(r[i_uf])))
    if not out.rows:
        raise ValueError(f"Cadastro de postos {period}: nenhuma linha reconhecida (leiaute inesperado).")
    return out


def fetch_postos(year: int, month: int = 12, refresh: bool = False) -> PostosMonth:
    period = f"{year}{month:02d}"
    raw = fetch(POSTOS_URL.format(period=period), namespace="bcb_postos", cache_key=period, suffix=".zip", refresh=refresh)
    return parse_postos(raw, period)


def is_cooperativa(segmento: str) -> bool:
    """Segmentos de cooperativas de crédito (exclui bancos cooperativos, que são bancos)."""
    s = segmento.lower()
    return "cooperativa" in s and "banco" not in s


# ------------------------------------------------------------------ SCR.data
def _range(url: str, start: int, end: int) -> bytes:
    r = client().get(url, headers={"Range": f"bytes={start}-{end}"})
    if r.status_code == 404:
        raise NotPublished(url)
    if r.status_code != 206:
        raise SourceUnavailable(f"{url}: o servidor não atendeu à leitura parcial (HTTP {r.status_code}).")
    return r.content


class _TailFile(io.RawIOBase):
    """Arquivo remoto somente leitura: o final (diretório do ZIP) fica em memória; o resto é lido sob demanda."""

    def __init__(self, url: str, size: int, tail: int = 200_000):
        self.url, self.size, self.pos = url, size, 0
        self.tail_start = max(0, size - tail)
        self.tail = _range(url, self.tail_start, size - 1)

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off
        return self.pos

    def read(self, n=-1):
        end = self.size if n is None or n < 0 else min(self.size, self.pos + n)
        if end <= self.pos:
            return b""
        if self.pos >= self.tail_start:
            data = self.tail[self.pos - self.tail_start:end - self.tail_start]
        else:
            data = _range(self.url, self.pos, end - 1)
        self.pos += len(data)
        return data


def fetch_scr_december(year: int, refresh: bool = False) -> dict:
    """Carteira ativa de dezembro por (UF do tomador, tipo de instituição), em reais.

    O arquivo anual tem ~400 MB; lê-se apenas o CSV de dezembro por requisições parciais (HTTP Range) e
    guarda-se em cache somente o agregado — o CSV bruto (≈ 300 MB) não é armazenado.
    """
    cache = settings.raw_dir / "bcb_scr" / f"scr_{year}12_uf_tcb.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))
    url = SCR_URL.format(year=year)
    head = client().head(url)
    if head.status_code == 404 or "html" in head.headers.get("content-type", ""):
        raise NotPublished(url)
    size = int(head.headers["content-length"])
    try:
        zf = zipfile.ZipFile(_TailFile(url, size))
    except zipfile.BadZipFile:
        # arquivo do ano corrente ainda em atualização na fonte, ou diretório fora do trecho lido
        log.warning("SCR.data: diretório do arquivo ilegível; ano ignorado", extra=ctx(ano=year, bytes=size))
        raise NotPublished(f"{url}: arquivo ilegível") from None
    members = [i for i in zf.infolist() if f"{year}12" in i.filename]
    if not members:
        raise NotPublished(f"{url}: dezembro de {year} ainda não publicado")
    info = members[0]
    if info.compress_type != zipfile.ZIP_DEFLATED:
        raise ValueError(f"SCR.data {year}: compressão inesperada ({info.compress_type}).")
    # cabeçalho local: 30 bytes fixos + nome + campo extra; os dados comprimidos vêm em seguida
    lh = _range(url, info.header_offset, info.header_offset + 29)
    n_name, n_extra = struct.unpack("<HH", lh[26:30])
    start = info.header_offset + 30 + n_name + n_extra
    tmp = settings.raw_dir / "bcb_scr" / f"_tmp_{year}12.csv"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    dec = zlib.decompressobj(-15)
    try:
        with client().stream("GET", url, headers={"Range": f"bytes={start}-{start + info.compress_size - 1}"}) as r, open(tmp, "wb") as f:
            if r.status_code != 206:
                raise SourceUnavailable(f"{url}: leitura parcial recusada (HTTP {r.status_code}).")
            for chunk in r.iter_bytes(1 << 20):
                f.write(dec.decompress(chunk))
            f.write(dec.flush())
        df = pl.read_csv(tmp, separator=";", columns=["uf", "tcb", "carteira_ativa"], infer_schema=False, encoding="utf8-lossy")
        agg = (df.with_columns(pl.col("carteira_ativa").str.replace_all(r"\.", "").str.replace(",", ".").cast(pl.Float64, strict=False),
                               pl.col("uf").str.strip_chars(), pl.col("tcb").str.strip_chars())
               .group_by("uf", "tcb").agg(pl.col("carteira_ativa").sum().alias("v"), pl.len().alias("n")))
        out = {"year": year, "member": info.filename, "rows": int(df.height),
               "data": [dict(uf=r["uf"], tcb=r["tcb"], valor=r["v"], linhas=r["n"]) for r in agg.sort("uf", "tcb").to_dicts()]}
    finally:
        tmp.unlink(missing_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    log.info("SCR.data agregado", extra=ctx(ano=year, linhas=out["rows"], mb_comprimido=info.compress_size // 2**20))
    return out
