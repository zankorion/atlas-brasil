"""Finanças municipais: receitas e despesas da Declaração de Contas Anuais (SICONFI/Tesouro Nacional)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from ..connectors import siconfi
from ..log import ctx, get_logger
from ..models import Territory
from ..store import ingestion_run, save_observations

log = get_logger("pipeline.siconfi")

# indicador do Atlas -> campo extraído da DCA
FIELDS = {
    "fin_receita_total": "receita_total", "fin_receita_corrente": "receita_corrente", "fin_receita_tributaria": "receita_tributaria",
    "fin_transferencias_correntes": "transferencias_correntes", "fin_iptu": "iptu", "fin_iss": "iss", "fin_itbi": "itbi", "fin_fpm": "fpm",
    "fin_despesa_total": "despesa_total", "fin_despesa_pessoal": "despesa_pessoal", "fin_investimentos": "investimentos",
    "fin_despesa_saude": "despesa_saude", "fin_despesa_educacao": "despesa_educacao",
}


def rows_for(records: dict[str, dict], period: str) -> dict[str, list]:
    """Linhas por indicador. Conta que não consta da declaração fica ausente (flag nd), nunca zero."""
    out: dict[str, list] = {k: [] for k in FIELDS}
    for code, rec in records.items():
        if not any(rec.get("itens", {}).values()):
            continue  # município não entregou a DCA do exercício: nenhuma observação
        for ind, field in FIELDS.items():
            v = rec.get(field)
            out[ind].append((code, "MUN", period, v, None if v is not None else "nd"))
    return out


def run(start: int = siconfi.FIRST_YEAR, end: int | None = None, refresh: bool = False) -> None:
    start = max(start, siconfi.FIRST_YEAR)
    end = end or date.today().year - 1
    for year in range(end, start - 1, -1):  # do mais recente para o mais antigo; cada exercício é gravado ao terminar
        with ingestion_run("siconfi", "tesouro_siconfi", exercicio=year) as (s, run_):
            codes = sorted(s.scalars(select(Territory.code).where(Territory.level == "MUN")))
            records, failures = siconfi.fetch_year(year, codes, refresh=refresh)
            delivered = sum(1 for r in records.values() if any(r.get("itens", {}).values()))
            rows = rows_for(records, str(year))
            info = dict(exercicio=year, municipios=len(codes), lidos=len(records), com_declaracao=delivered, falhas_de_rede=failures)
            log.info("SICONFI: exercício lido", extra=ctx(**info))
            run_.publication = f"DCA {year} — {delivered} de {len(codes)} municípios com declaração"
            run_.params = {**run_.params, **info}
            for ind, r in rows.items():
                save_observations(s, run_, ind, r)
