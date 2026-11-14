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


# Uma declaração é deixada de fora quando é contabilmente impossível por si só — sem comparar com outros municípios:
RATIO_MIN, RATIO_MAX = 0.2, 5.0  # receita total / despesa total


def inconsistency(rec: dict) -> str | None:
    """Motivo pelo qual a declaração é inconsistente, ou None. Regras deliberadamente conservadoras."""
    rt, rc, dt = rec.get("receita_total"), rec.get("receita_corrente"), rec.get("despesa_total")
    if rt is not None and rt <= 0:
        return "receita total nula ou negativa (deduções maiores que a receita bruta)"
    if rc is not None and rc <= 0:
        return "receita corrente nula ou negativa (deduções maiores que a receita bruta)"
    if rt is not None and dt is not None and dt > 0 and not (RATIO_MIN <= rt / dt <= RATIO_MAX):
        return f"receita total equivale a {rt / dt:.1f} vezes a despesa total (aceito: de {RATIO_MIN} a {RATIO_MAX})".replace(".", ",")
    if rt is not None and rt > 0 and dt is not None and dt <= 0:
        return "despesa total nula com receita declarada"
    return None


def rows_for(records: dict[str, dict], period: str) -> tuple[dict[str, list], list[dict]]:
    """Linhas por indicador e a lista das declarações deixadas de fora por inconsistência.

    Conta que não consta da declaração fica ausente (flag nd), nunca zero. Declaração inconsistente tem todos os
    valores registrados como ausentes (flag inc): o que foi declarado não é corrigido nem estimado, e fica
    guardado, com o motivo, no histórico da carga.
    """
    out: dict[str, list] = {k: [] for k in FIELDS}
    left_out: list[dict] = []
    for code, rec in records.items():
        if not any(rec.get("itens", {}).values()):
            continue  # município não entregou a DCA do exercício: nenhuma observação
        why = inconsistency(rec)
        if why:
            left_out.append(dict(codigo=code, motivo=why, receita_total_declarada=rec.get("receita_total"),
                                 despesa_total_declarada=rec.get("despesa_total")))
        for ind, field in FIELDS.items():
            v = None if why else rec.get(field)
            out[ind].append((code, "MUN", period, v, "inc" if why else None if v is not None else "nd"))
    return out, left_out


def run(start: int = siconfi.FIRST_YEAR, end: int | None = None, refresh: bool = False) -> None:
    start = max(start, siconfi.FIRST_YEAR)
    end = end or date.today().year - 1
    for year in range(end, start - 1, -1):  # do mais recente para o mais antigo; cada exercício é gravado ao terminar
        with ingestion_run("siconfi", "tesouro_siconfi", exercicio=year) as (s, run_):
            codes = sorted(s.scalars(select(Territory.code).where(Territory.level == "MUN")))
            records, failures = siconfi.fetch_year(year, codes, refresh=refresh)
            delivered = sum(1 for r in records.values() if any(r.get("itens", {}).values()))
            rows, left_out = rows_for(records, str(year))
            info = dict(exercicio=year, municipios=len(codes), lidos=len(records), com_declaracao=delivered, falhas_de_rede=failures,
                        inconsistentes=len(left_out))
            log.info("SICONFI: exercício lido", extra=ctx(**info))
            run_.publication = (f"DCA {year} — {delivered} de {len(codes)} municípios com declaração"
                                + (f"; {len(left_out)} deixadas de fora por inconsistência" if left_out else ""))
            run_.params = {**run_.params, **info, "declaracoes_inconsistentes": left_out}
            for ind, r in rows.items():
                save_observations(s, run_, ind, r)
