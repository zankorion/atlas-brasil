"""SICONFI (Tesouro Nacional) — Declaração de Contas Anuais (DCA) dos municípios.

A API só responde por ente (`id_ente`), um anexo por consulta. As respostas brutas são grandes (dezenas de KB por
município e anexo), então o cache guarda apenas os valores extraídos, em um arquivo JSONL por exercício.

O plano de contas mudou de codificação ao longo dos anos (2014–2017, 2018–2021, 2022+). Por isso:
  * grandes grupos são achados pela posição no plano de contas (1 = receitas correntes, 1.1 = tributária, …),
    que é estável;
  * impostos e o FPM são achados pelo nome da conta, dentro do grupo certo, somando só as contas que não têm
    uma conta-mãe também encontrada (evita contar pai e filhas).
"""
from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
from pathlib import Path

import httpx

from ..config import settings
from ..log import ctx, get_logger
from .base import client

log = get_logger("connector.siconfi")
URL = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/dca"
ANEXOS = {"receitas": "DCA-Anexo I-C", "despesas": "DCA-Anexo I-D", "funcoes": "DCA-Anexo I-E"}
FIRST_YEAR = 2014  # exercícios anteriores usam outros anexos na API
COL_RECEITA = "Receitas Brutas Realizadas"
COL_DESPESA = "Despesas Empenhadas"


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def position(cod_conta: str) -> str:
    """Posição no plano de contas, sem prefixo e sem zeros finais: 'RO1.1.0.0.00.0.0' -> '1.1'."""
    parts = re.sub(r"^[A-Z]+", "", cod_conta or "").split(".")
    while parts and set(parts[-1]) <= {"0"}:
        parts.pop()
    return ".".join(parts)


def _net_by_account(items: list[dict]) -> dict[tuple[str, str], float]:
    """Receita líquida por conta: bruta realizada menos todas as colunas de dedução. Só contas orçamentárias (RO)."""
    out: dict[tuple[str, str], float] = {}
    gross: set[tuple[str, str]] = set()
    for i in items:
        cod, col, v = i.get("cod_conta") or "", i.get("coluna") or "", i.get("valor")
        if v is None or not (cod.startswith("RO") or cod == "TotalReceitas"):
            continue
        key = (cod, i.get("conta") or "")
        if col == COL_RECEITA:
            out[key] = out.get(key, 0.0) + float(v)
            gross.add(key)
        elif "dedu" in _norm(col):
            out[key] = out.get(key, 0.0) - float(v)
    return {k: v for k, v in out.items() if k in gross}


def _sum_tops(accounts: dict[tuple[str, str], float], group: str, name_has: str, name_starts: str | None = None) -> float | None:
    """Soma as contas do grupo cujo nome contém `name_has`, ignorando as que descendem de outra conta encontrada."""
    found: dict[str, float] = {}
    for (cod, conta), v in accounts.items():
        pos = position(cod)
        if not (pos == group or pos.startswith(group + ".")):
            continue
        label = _norm(re.sub(r"^[\d. ]+-?\s*", "", conta))
        if name_has in label and (name_starts is None or label.startswith(name_starts)):
            found[pos] = found.get(pos, 0.0) + v
    tops = [p for p in found if not any(p != q and p.startswith(q + ".") for q in found)]
    return sum(found[p] for p in tops) if tops else None


def extract_receitas(items: list[dict]) -> dict[str, float | None]:
    acc = _net_by_account(items)
    by_pos: dict[str, float] = {}
    for (cod, _), v in acc.items():
        if cod.startswith("RO"):
            by_pos[position(cod)] = v
    total = [v for (cod, _), v in acc.items() if cod == "TotalReceitas"]
    return dict(
        receita_total=max(total) if total else None,
        receita_corrente=by_pos.get("1"),
        receita_capital=by_pos.get("2"),
        receita_tributaria=by_pos.get("1.1"),
        transferencias_correntes=by_pos.get("1.7"),
        iptu=_sum_tops(acc, "1.1", "propriedade predial", "imposto"),
        iss=_sum_tops(acc, "1.1", "servicos de qualquer natureza", "imposto"),
        itbi=_sum_tops(acc, "1.1", "inter vivos", "imposto"),
        fpm=_sum_tops(acc, "1.7", "fundo de participacao dos municipios"),
    )


def extract_despesas(items: list[dict]) -> dict[str, float | None]:
    by_pos: dict[str, float] = {}
    total = None
    for i in items:
        if i.get("coluna") != COL_DESPESA or i.get("valor") is None:
            continue
        cod = i.get("cod_conta") or ""
        if cod == "TotalDespesas":
            total = float(i["valor"]) if total is None else max(total, float(i["valor"]))
        elif cod.startswith("DO"):
            by_pos[position(cod)] = float(i["valor"])
    return dict(despesa_total=total, despesa_corrente=by_pos.get("3"), despesa_capital=by_pos.get("4"),
                despesa_pessoal=by_pos.get("3.1"), investimentos=by_pos.get("4.4"))


def extract_funcoes(items: list[dict]) -> dict[str, float | None]:
    out: dict[str, float | None] = {"despesa_saude": None, "despesa_educacao": None}
    for i in items:
        if i.get("coluna") != COL_DESPESA or i.get("valor") is None:
            continue
        label = _norm(i.get("conta") or "")
        key = "despesa_saude" if re.match(r"^10 - saude", label) else "despesa_educacao" if re.match(r"^12 - educacao", label) else None
        if key:  # a função pode repetir no bloco intraorçamentário: vale a maior (o total exceto intra)
            v = float(i["valor"])
            out[key] = v if out[key] is None else max(out[key], v)
    return out


EXTRACT = {"receitas": extract_receitas, "despesas": extract_despesas, "funcoes": extract_funcoes}


# A API limita a taxa de consultas (HTTP 429). Todas as threads compartilham um intervalo mínimo entre
# requisições e, ao receber 429, uma pausa comum antes de tentar de novo.
MIN_INTERVAL = 0.3  # segundos entre requisições (cerca de 3 por segundo)
PAUSE_429 = 60.0
_pace = threading.Lock()
_next_at = 0.0


def _wait_turn() -> None:
    global _next_at
    with _pace:
        now = time.monotonic()
        start = max(now, _next_at)
        _next_at = start + MIN_INTERVAL
    if start > now:
        time.sleep(start - now)


def _back_off() -> None:
    global _next_at
    with _pace:
        _next_at = max(_next_at, time.monotonic() + PAUSE_429)


def _get(year: int, code: str, anexo: str) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        last: Exception | None = None
        for attempt in range(settings.http_retries + 4):
            try:
                _wait_turn()
                r = client().get(URL, params={"an_exercicio": year, "id_ente": code, "no_anexo": anexo, "offset": offset}, timeout=90)
                if r.status_code == 429:
                    last = RuntimeError("HTTP 429 (limite de consultas)")
                    _back_off()
                    continue
                r.raise_for_status()
                d = r.json()
                break
            except (httpx.HTTPError, ValueError) as e:
                last = e
                time.sleep(2**min(attempt, 4))
        else:
            raise RuntimeError(f"SICONFI {year} {code} {anexo}: {last}")
        items += d.get("items", [])
        if not d.get("hasMore"):
            return items
        offset += d.get("limit", 5000)


def fetch_ente(year: int, code: str) -> dict:
    """Valores extraídos dos três anexos de um município. `itens` = linhas recebidas por anexo (0 = não declarado)."""
    rec: dict = {"code": code, "itens": {}}
    for key, anexo in ANEXOS.items():
        items = _get(year, code, anexo)
        rec["itens"][key] = len(items)
        rec.update(EXTRACT[key](items) if items else {k: None for k in EXTRACT[key]([])})
    return rec


def cache_file(year: int) -> Path:
    d = settings.raw_dir / "siconfi"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"dca_municipios_{year}.jsonl"


def load_year(year: int) -> dict[str, dict]:
    p = cache_file(year)
    out: dict[str, dict] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["code"]] = r
    return out


def fetch_year(year: int, codes: list[str], refresh: bool = False, workers: int = 3) -> tuple[dict[str, dict], int]:
    """Lê (ou completa) o exercício; devolve (registros por município, falhas de rede)."""
    from concurrent.futures import ThreadPoolExecutor

    p = cache_file(year)
    if refresh and p.exists():
        p.unlink()
    have = load_year(year)
    todo = [c for c in codes if c not in have]
    lock = threading.Lock()
    failures = 0

    def work(code: str) -> None:
        nonlocal failures
        try:
            rec = fetch_ente(year, code)
        except RuntimeError as e:
            with lock:
                failures += 1
            log.warning("SICONFI: município não lido", extra=ctx(ano=year, codigo=code, erro=str(e)[:160]))
            return
        with lock:
            have[code] = rec
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    if todo:
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(work, todo))
    return have, failures
