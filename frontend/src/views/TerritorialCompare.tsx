"use client";
import Link from "next/link";
import { useMoney } from "@/lib/money";
import { useCallback, useState } from "react";
import { Chart, type Theme } from "@/components/Chart";
import { IndicatorSelect, useCatalog } from "@/components/pickers";
import { Button, Card, MoneySelect, Field, Loading, Notice, Provenance } from "@/components/ui";
import { qs, useApi, type VarMeta } from "@/lib/api";
import { lineOption, type Serie } from "@/lib/charts";
import { download, fmtNum, fmtValue, periodLabel } from "@/lib/format";

type CmpResp = {
  territories: { code: string; name: string; level: string; uf: string | null }[];
  rows: { meta: VarMeta; cells: Record<string, { value: number | null; period: string | null; rel_first: number | null }>; mixed_periods: boolean }[];
};
const DEFAULT_VARS = ["populacao", "pib_per_capita", "part_industria", "part_adm", "credito_pc", "depositos_pc", "icr", "cooperativas_credito", "pct_domicilios_proprios", "gini_fundiario"];

/** Comparação de vários territórios: tabela com o valor mais recente de cada indicador e gráfico de evolução. */
export function TerritorialCompare({ terrs, focus }: { terrs: { code: string; level: string }[]; focus?: string }) {
  const { indicators } = useCatalog();
  const [vars, setVars] = useState<string[]>(DEFAULT_VARS);
  const [add, setAdd] = useState("pib_nominal");
  const [real, setReal] = useMoney();
  const [picked, setPicked] = useState<string | null>(null);
  const codes = terrs.map((t) => t.code).join(",");
  const levels = [...new Set(terrs.map((t) => t.level))];
  // só indicadores disponíveis em todos os níveis selecionados
  const usable = vars.filter((v) => v.startsWith("=") || levels.every((l) => indicators.find((i) => i.id === v)?.levels.includes(l) ?? true));
  const list = focus && !usable.includes(focus) ? [focus, ...usable] : usable;
  const chartVar = picked && list.includes(picked) ? picked : focus ?? list[0] ?? "pib_per_capita";
  const cmp = useApi<CmpResp>(codes && list.length ? `/api/compare${qs({ vars: list.join(";"), codes, real })}` : null);
  const ser = useApi<{ meta: VarMeta; series: Serie[] }>(codes ? `/api/series${qs({ var: chartVar, codes, real })}` : null);
  const build = useCallback((t: Theme) => (ser.data ? lineOption(t, ser.data.series, ser.data.meta, "nivel") : {}), [ser.data]);

  const csv = () => {
    if (!cmp.data) return;
    const lines = ["# Atlas Econômico e Social do Brasil — comparação territorial", "# Células vazias são valores ausentes — não equivalem a zero.",
      ["indicador", "unidade", ...cmp.data.territories.flatMap((t) => [`"${t.name}"`, `"${t.name} (período)"`])].join(",")];
    cmp.data.rows.forEach((r) => lines.push([`"${r.meta.name}"`, `"${r.meta.unit}${r.meta.real ? " (real)" : ""}"`,
      ...cmp.data!.territories.flatMap((t) => [r.cells[t.code].value ?? "", r.cells[t.code].period ?? ""])].join(",")));
    download("atlas_comparacao.csv", "﻿" + lines.join("\n"), "text/csv");
  };

  return (
    <section aria-label="Comparação dos territórios selecionados" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h2 className="font-serif text-2xl font-semibold tracking-tight">Comparação — {terrs.length} territórios</h2>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Adicionar indicador à tabela">
            <div className="flex gap-2">
              <IndicatorSelect value={add} onChange={setAdd} frequency="A" />
              <Button onClick={() => !vars.includes(add) && vars.length < 12 && setVars([...vars, add])}>Adicionar</Button>
            </div>
          </Field>
          <div className="pb-1.5"><MoneySelect value={real} onChange={setReal} /></div>
        </div>
      </div>
      {cmp.error && <Notice kind="error">{cmp.error}</Notice>}
      {cmp.loading && !cmp.data && <Loading />}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {cmp.data && (
          <Card title="Valor mais recente de cada território" actions={<Button onClick={csv}>Exportar CSV</Button>}>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted">
                  <tr><th className="py-1.5 pr-3">Indicador</th>
                    {cmp.data.territories.map((t) => <th key={t.code} className="px-3 py-1.5 text-right"><Link className="hover:text-accent hover:underline" href={`/territorios/${t.code}`}>{t.name}{t.uf ? ` (${t.uf})` : ""}</Link></th>)}
                    <th /></tr>
                </thead>
                <tbody>
                  {cmp.data.rows.map((r) => (
                    <tr key={r.meta.spec} className="border-t border-line align-top">
                      <td className="py-1.5 pr-3">
                        <button type="button" className={`text-left hover:text-accent hover:underline ${chartVar === r.meta.spec ? "font-medium text-accent" : ""}`} onClick={() => setPicked(r.meta.spec)} title="Mostrar no gráfico">{r.meta.name}</button>
                        <div className="text-xs text-muted">{r.meta.unit}{r.meta.real ? " · real" : ""}{r.mixed_periods && <span className="text-warn"> · períodos diferentes</span>}</div>
                      </td>
                      {cmp.data!.territories.map((t, i) => {
                        const c = r.cells[t.code];
                        return (
                          <td key={t.code} className="num px-3 py-1.5 text-right">
                            {c.value === null ? <span className="font-sans text-muted">sem dado</span> : fmtValue(c.value, r.meta, { unit: false })}
                            <div className="text-xs text-muted">{c.value !== null && periodLabel(c.period)}{i > 0 && c.rel_first !== null ? ` · ${c.rel_first > 0 ? "+" : ""}${fmtNum(c.rel_first, 1)}%` : ""}</div>
                          </td>
                        );
                      })}
                      <td className="py-1.5 pl-2 text-right">{r.meta.spec !== focus && <button type="button" aria-label={`Remover ${r.meta.name}`} className="text-muted hover:text-danger" onClick={() => setVars(vars.filter((v) => v !== r.meta.spec))}>×</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-xs leading-relaxed text-muted">
              A porcentagem abaixo de cada valor é a diferença relativa em relação ao primeiro território ({cmp.data.territories[0]?.name}).
              Cada célula mostra o período de referência; quando os períodos diferem entre territórios, a linha é sinalizada.
              {usable.length < vars.length && " Indicadores indisponíveis em algum dos níveis territoriais selecionados foram omitidos."}
            </p>
          </Card>
        )}
        {ser.data && (
          <Card title={`Evolução — ${ser.data.meta.name} (${ser.data.meta.unit})`}>
            <Chart build={build} height={380} renderer="svg" exportName="atlas_comparacao_serie" ariaLabel="Evolução comparada" />
            <p className="mt-1 text-xs text-muted">Clique no nome de um indicador da tabela para trocá-lo no gráfico.</p>
            <div className="mt-3"><Provenance meta={ser.data.meta} /></div>
          </Card>
        )}
      </div>
    </section>
  );
}
