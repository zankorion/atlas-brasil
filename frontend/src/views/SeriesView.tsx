"use client";
import { useMoney } from "@/lib/money";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Chart, type Theme } from "@/components/Chart";
import { IndicatorSelect, TerritoryChips, TerritorySearch, useCatalog } from "@/components/pickers";
import { Button, Card, MoneySelect, Field, Loading, Notice, Page, Provenance, Seg } from "@/components/ui";
import { api, qs, useApi, type Territory, type VarMeta } from "@/lib/api";
import { allPeriods, lineOption, seriesCsv, serieLabel, transformSeries, type Serie, type Transform } from "@/lib/charts";
import { download, fmtValue, periodLabel, slug } from "@/lib/format";

type Resp = { meta: VarMeta; series: Serie[]; territory_changes: { code: string; year: number; note: string }[] };
const BR: Territory = { code: "BR", level: "BR", name: "Brasil", sigla: "BR", uf: null, uf_code: null };

export default function SeriesView() {
  const sp = useSearchParams();
  const { indicators } = useCatalog();
  const [freq, setFreq] = useState<"A" | "M">((sp.get("freq") as "A" | "M") ?? "A");
  const [spec, setSpec] = useState(sp.get("var") ?? "pib_per_capita");
  const [terrs, setTerrs] = useState<Territory[]>([BR]);
  const [real, setReal] = useMoney();
  const [transform, setTransform] = useState<Transform>("nivel");

  // Territórios iniciais vindos da URL (?codes=...)
  useEffect(() => {
    const codes = sp.get("codes");
    if (!codes) return;
    Promise.all(codes.split(",").slice(0, 8).map((c) => api<Territory>(`/api/territories/${c}`).catch(() => null)))
      .then((ts) => { const ok = ts.filter(Boolean) as Territory[]; if (ok.length) setTerrs(ok); });
  }, [sp]);

  const ind = indicators.find((i) => i.id === spec);
  const monthly = (ind?.frequency ?? freq) === "M";
  const codes = monthly ? "BR" : terrs.map((t) => t.code).join(",");
  const { data, error, loading } = useApi<Resp>(codes ? `/api/series${qs({ var: spec, codes, real })}` : null);
  const ok = data && data.meta.spec === spec ? data : null;

  const marks = useMemo(() => {
    if (!ok) return [];
    const m = ok.meta.breaks.map((b) => ({ period: b.period, label: "quebra de série" }));
    ok.territory_changes.forEach((c) => m.push({ period: String(c.year), label: "alteração territorial" }));
    return m;
  }, [ok]);
  const build = useCallback((t: Theme) => (ok ? lineOption(t, ok.series, ok.meta, transform, marks) : {}), [ok, transform, marks]);
  const periods = ok ? allPeriods(ok.series) : [];
  const tr = ok ? transformSeries(ok.series, transform, periods) : null;
  const empty = ok && ok.series.every((s) => s.points.length === 0);

  return (
    <Page title="Séries Históricas" lead="Evolução dos indicadores desde o Plano Real. Cada série preserva sua data inicial efetiva; lacunas no gráfico são anos sem publicação — não são interpoladas.">
      <div className="grid gap-5 lg:grid-cols-[20rem_1fr]">
        <Card title="Seleção">
          <div className="space-y-4">
            <Field label="Periodicidade">
              <Seg label="Periodicidade" value={freq} onChange={(f) => { setFreq(f); setSpec(f === "M" ? "selic" : "pib_per_capita"); }}
                options={[{ value: "A", label: "Anual (territorial)" }, { value: "M", label: "Mensal (Brasil)" }]} />
            </Field>
            <Field label="Indicador">
              <IndicatorSelect value={spec} onChange={setSpec} frequency={freq} allowCustom={freq === "A"} />
            </Field>
            {!monthly && (
              <Field label="Territórios (até 8)">
                <TerritorySearch onPick={(t) => terrs.length < 8 && setTerrs([...terrs, t])} exclude={terrs.map((t) => t.code)} />
                <TerritoryChips items={terrs} onRemove={(c) => setTerrs(terrs.filter((t) => t.code !== c))} />
              </Field>
            )}
            <Field label="Transformação">
              <Seg label="Transformação" value={transform} onChange={setTransform}
                options={[{ value: "nivel", label: "Nível" }, { value: "indice", label: "Base 100" }, { value: "variacao", label: "Var. % anual" }]} />
            </Field>
            <MoneySelect value={real} onChange={setReal} disabled={!ind?.monetary && !spec.startsWith("=")} />
            {ind && !ind.monetary && <p className="text-xs text-muted">O deflacionamento só se aplica a valores monetários nominais.</p>}
          </div>
        </Card>
        <div className="space-y-4">
          {error && <Notice kind="error">{error}</Notice>}
          {!ok && loading && <Loading />}
          {!monthly && terrs.length === 0 && <Notice>Adicione ao menos um território.</Notice>}
          {ok && (
            <Card title={`${ok.meta.name} — ${transform === "nivel" ? ok.meta.unit : transform === "indice" ? `índice, base 100 em ${periodLabel(tr?.base)}` : "variação % sobre o ano anterior"}`}>
              {empty ? <Notice>Não há observações deste indicador para os territórios selecionados.</Notice> : (
                <Chart build={build} height={420} renderer="svg" exportName={`atlas_serie_${slug(ok.meta.short_name)}`} ariaLabel={`Série histórica de ${ok.meta.name}`} />
              )}
              {transform === "indice" && tr && !tr.base && <Notice kind="warn">Não há um período em que todas as séries tenham valor; a base 100 não pôde ser calculada.</Notice>}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button onClick={() => download(`atlas_serie_${slug(ok.meta.short_name)}.csv`, seriesCsv(ok.series, ok.meta, transform), "text/csv")}>Exportar dados (CSV)</Button>
              </div>
              <div className="mt-4">
                <Provenance meta={ok.meta} extra={<>
                  {ok.meta.breaks.map((b) => <p key={b.period}><span className="font-medium text-warn">Quebra metodológica em {b.period}:</span> {b.note}</p>)}
                  {ok.territory_changes.map((c) => <p key={c.code + c.year}><span className="font-medium text-warn">Alteração territorial:</span> {c.note} Valores anteriores e posteriores referem-se a áreas diferentes.</p>)}
                </>} />
              </div>
            </Card>
          )}
          {ok && !empty && tr && (
            <Card title="Tabela">
              <div className="max-h-96 overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-surface text-left text-xs uppercase tracking-wide text-muted">
                    <tr><th className="py-1.5 pr-3">Período</th>{ok.series.map((s) => <th key={s.code} className="px-3 py-1.5 text-right">{serieLabel(s)}</th>)}</tr>
                  </thead>
                  <tbody>
                    {[...periods].reverse().map((p) => {
                      const j = periods.indexOf(p);
                      return (
                        <tr key={p} className="border-t border-line">
                          <td className="num py-1 pr-3">{periodLabel(p)}</td>
                          {tr.rows.map((r, i) => (
                            <td key={i} className="num px-3 py-1 text-right">
                              {r[j] === null ? <span className="text-muted" title="Sem dado">—</span> : fmtValue(r[j], transform === "nivel" ? ok.meta : { unit: transform === "indice" ? "índice" : "%", decimals: 1 }, { unit: transform === "variacao" })}
                            </td>
                          ))}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </div>
      </div>
    </Page>
  );
}
