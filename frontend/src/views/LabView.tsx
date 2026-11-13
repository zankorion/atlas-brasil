"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { axis, baseOption, Chart, type Theme } from "@/components/Chart";
import { IndicatorSelect, LEVEL_OPTIONS, PeriodSelect, UfSelect, useCatalog, usePeriods } from "@/components/pickers";
import { Button, Card, Check, Field, Loading, Notice, Page, Provenance, Select, Stat, Tabs, inputCls } from "@/components/ui";
import { API, getCustom, post, qs, saveCustom, useApi, type Stats, type VarMeta } from "@/lib/api";
import { axisFmt, download, fmtNum, fmtP, fmtValue, LEVEL_NAMES, periodLabel } from "@/lib/format";

type Corr = { n: number; pearson: { r: number; p: number } | null; spearman: { rho: number; p: number } | null; note?: string };
type Ols = { n: number; intercept: number; slope: number; r2: number; p_slope: number; se_slope: number; rmse: number } | null;
const LVL_NO_REGIAO = LEVEL_OPTIONS.filter((l) => l.value !== "REGIAO");

function usePeriod(spec: string, level: string) {
  const { periods } = usePeriods(spec, level);
  const [p, setP] = useState<string | null>(null);
  const cur = p && periods.includes(p) ? p : periods[periods.length - 1] ?? null;
  return { periods, period: cur, setPeriod: setP };
}

// ------------------------------------------------------------------ Dispersão e correlação
type ScatterResp = {
  x: VarMeta; y: VarMeta; level: string; period_x: string; period_y: string; log_x: boolean; log_y: boolean;
  sample: { n: number; n_territories: number; n_in_scope: number; missing_x: number; missing_y: number; missing_both: number; dropped_nonpositive_log: number };
  correlation: Corr; regression: Ols; regression_note: string; notes: string[]; warning: string;
  points: { code: string; name: string; uf: string | null; x: number; y: number }[];
};

function Scatter() {
  const sp = useSearchParams();
  const router = useRouter();
  const [x, setX] = useState(sp.get("x") ?? "pib_per_capita");
  const [y, setY] = useState(sp.get("y") ?? "credito_pc");
  const [level, setLevel] = useState("MUN");
  const [uf, setUf] = useState("");
  const [real, setReal] = useState(false);
  const [logX, setLogX] = useState(true);
  const [logY, setLogY] = useState(true);
  const [popMin, setPopMin] = useState("");
  const px = usePeriods(x, level), py = usePeriods(y, level);
  const common = useMemo(() => px.periods.filter((p) => py.periods.includes(p)), [px.periods, py.periods]);
  const [period, setPeriod] = useState<string | null>(null);
  const cur = period && common.includes(period) ? period : common[common.length - 1] ?? null;
  const body = cur ? { x, y, level, period: cur, real, log_x: logX, log_y: logY, uf: uf || null, pop_min: popMin ? Number(popMin) : null } : undefined;
  const { data, error, loading } = useApi<ScatterResp>(cur ? "/api/lab/scatter" : null, body);
  const ok = data && data.x.spec === x && data.y.spec === y ? data : null;
  const build = useCallback((t: Theme) => {
    if (!ok) return {};
    const r = ok.regression;
    const xs = ok.points.map((p) => p.x);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    const fx = (v: number) => (ok.log_x ? Math.log(v) : v), gy = (v: number) => (ok.log_y ? Math.exp(v) : v);
    const line = r && xs.length ? Array.from({ length: 40 }, (_, i) => {
      const v = ok.log_x ? Math.exp(Math.log(lo) + ((Math.log(hi) - Math.log(lo)) * i) / 39) : lo + ((hi - lo) * i) / 39;
      return [v, gy(r.intercept + r.slope * fx(v))];
    }) : [];
    const ax = (m: VarMeta, log: boolean, p: string) => ({
      type: log ? "log" : "value", scale: true, name: `${m.short_name} (${m.unit}${m.real ? ", real" : ""}) · ${p}${log ? " · escala log" : ""}`, nameLocation: "middle",
      ...axis(t, { axisLabel: { color: t.muted, fontSize: 11, formatter: (v: number) => axisFmt(v) } }),
    });
    return {
      ...baseOption(t), legend: { show: false }, grid: { left: 28, right: 20, top: 16, bottom: 36, containLabel: true },
      tooltip: { ...(baseOption(t).tooltip as object), trigger: "item", formatter: (p: unknown) => {
        const q = p as { seriesIndex: number; dataIndex: number };
        if (q.seriesIndex !== 0) return "";
        const d = ok.points[q.dataIndex];
        return `<b>${d.name}${d.uf ? " (" + d.uf + ")" : ""}</b><br/>${ok.x.short_name}: ${fmtValue(d.x, ok.x)}<br/>${ok.y.short_name}: ${fmtValue(d.y, ok.y)}`;
      } },
      xAxis: { ...ax(ok.x, ok.log_x, ok.period_x), nameGap: 28 }, yAxis: { ...ax(ok.y, ok.log_y, ok.period_y), nameGap: 52 },
      series: [
        { type: "scatter", data: ok.points.map((p) => [p.x, p.y]), symbolSize: ok.points.length > 1500 ? 4 : 7, itemStyle: { color: t.accent, opacity: ok.points.length > 1500 ? 0.45 : 0.75 }, large: false },
        { type: "line", data: line, showSymbol: false, silent: true, lineStyle: { color: t.series[1], width: 2 }, tooltip: { show: false } },
      ],
    };
  }, [ok]);
  const c = ok?.correlation, r = ok?.regression;
  const csv = () => {
    if (!ok) return;
    const head = ["# Atlas Econômico e Social do Brasil — dispersão", `# X: ${ok.x.name} (${ok.x.unit}) — ${ok.period_x}`, `# Y: ${ok.y.name} (${ok.y.unit}) — ${ok.period_y}`,
      `# Fontes: ${[...ok.x.sources, ...ok.y.sources].map((s) => s.source + " — " + s.dataset).join("; ")}`, `# n = ${ok.sample.n}; territórios sem dado em X ou Y foram excluídos`, "codigo_ibge,territorio,uf,x,y"];
    download("atlas_dispersao.csv", "﻿" + head.concat(ok.points.map((p) => `${p.code},"${p.name}",${p.uf ?? ""},${p.x},${p.y}`)).join("\n"), "text/csv");
  };
  return (
    <div className="grid gap-5 xl:grid-cols-[21rem_1fr]">
      <Card title="Variáveis">
        <div className="space-y-3">
          <Field label="Eixo X"><IndicatorSelect value={x} onChange={setX} level={level} frequency="A" label="Eixo X" /></Field>
          <Check checked={logX} onChange={setLogX} label="Escala logarítmica em X" />
          <Field label="Eixo Y"><IndicatorSelect value={y} onChange={setY} level={level} frequency="A" label="Eixo Y" /></Field>
          <Check checked={logY} onChange={setLogY} label="Escala logarítmica em Y" />
          <div className="grid grid-cols-2 gap-3">
            <Field label="Nível"><Select value={level} onChange={setLevel} options={LEVEL_OPTIONS} /></Field>
            <Field label="Período"><PeriodSelect value={cur} onChange={setPeriod} periods={common} /></Field>
          </div>
          <Field label="Recorte"><UfSelect value={uf} onChange={setUf} /></Field>
          <Field label="População mínima" hint="Opcional. Filtra pelo porte populacional."><input className={inputCls} inputMode="numeric" value={popMin} onChange={(e) => setPopMin(e.target.value.replace(/\D/g, ""))} placeholder="ex.: 50000" /></Field>
          <Check checked={real} onChange={setReal} label="Valores monetários reais (IPCA)" />
          {!px.loading && !py.loading && common.length === 0 && <Notice kind="warn">As duas variáveis não têm nenhum período em comum neste nível territorial.</Notice>}
        </div>
      </Card>
      <div className="space-y-4">
        {error && <Notice kind="error">{error}</Notice>}
        {loading && !ok && <Loading />}
        {ok && (
          <>
            <Card title={`${ok.y.short_name} × ${ok.x.short_name} — ${LEVEL_NAMES[ok.level]}`} actions={<Button onClick={csv}>Exportar pontos (CSV)</Button>}>
              <Chart build={build} height={480} exportName="atlas_dispersao" ariaLabel={`Dispersão entre ${ok.x.name} e ${ok.y.name}`}
                onPick={(i, s) => s === 0 && ok.points[i] && router.push(`/territorios/${ok.points[i].code}`)} />
              <p className="mt-1 text-xs text-muted">Cada ponto é um território; clique para abrir o perfil. A linha é o ajuste linear {ok.regression_note.replace("Regressão estimada ", "").replace(".", "")}.</p>
            </Card>
            <div className="grid gap-4 md:grid-cols-3">
              <Card title="Amostra">
                <dl className="space-y-1 text-sm">
                  <div className="flex justify-between"><dt>Territórios na análise (n)</dt><dd className="num font-medium">{fmtNum(ok.sample.n, 0)}</dd></div>
                  <div className="flex justify-between text-muted"><dt>No recorte</dt><dd className="num">{fmtNum(ok.sample.n_in_scope, 0)}</dd></div>
                  <div className="flex justify-between text-muted"><dt>Sem dado em X</dt><dd className="num">{ok.sample.missing_x}</dd></div>
                  <div className="flex justify-between text-muted"><dt>Sem dado em Y</dt><dd className="num">{ok.sample.missing_y}</dd></div>
                  <div className="flex justify-between text-muted"><dt>Sem dado em ambos</dt><dd className="num">{ok.sample.missing_both}</dd></div>
                  {ok.sample.dropped_nonpositive_log > 0 && <div className="flex justify-between text-warn"><dt>Excluídos (valor ≤ 0 em escala log)</dt><dd className="num">{ok.sample.dropped_nonpositive_log}</dd></div>}
                </dl>
                <p className="mt-2 text-xs text-muted">Territórios com dado ausente são excluídos — nunca tratados como zero.</p>
              </Card>
              <Card title="Correlação">
                {c?.pearson ? (
                  <dl className="space-y-2 text-sm">
                    <div><dt className="text-xs uppercase tracking-wide text-muted">Pearson (linear{ok.log_x || ok.log_y ? ", nas escalas transformadas" : ""})</dt><dd className="num text-lg">r = {fmtNum(c.pearson.r, 3)} <span className="text-xs text-muted">p {fmtP(c.pearson.p)}</span></dd></div>
                    <div><dt className="text-xs uppercase tracking-wide text-muted">Spearman (postos)</dt><dd className="num text-lg">ρ = {fmtNum(c.spearman!.rho, 3)} <span className="text-xs text-muted">p {fmtP(c.spearman!.p)}</span></dd></div>
                  </dl>
                ) : <p className="text-sm text-muted">{c?.note ?? "Amostra insuficiente."}</p>}
              </Card>
              <Card title="Regressão linear (MQO)">
                {r ? (
                  <dl className="space-y-1 text-sm">
                    <div className="num">{ok.log_y ? "ln(Y)" : "Y"} = {fmtNum(r.intercept, 3)} {r.slope >= 0 ? "+" : "−"} {fmtNum(Math.abs(r.slope), 4)} · {ok.log_x ? "ln(X)" : "X"}</div>
                    <div className="flex justify-between"><dt>R²</dt><dd className="num">{fmtNum(r.r2, 3)}</dd></div>
                    <div className="flex justify-between"><dt>Erro-padrão da inclinação</dt><dd className="num">{fmtNum(r.se_slope, 4)}</dd></div>
                    <div className="flex justify-between"><dt>Valor-p da inclinação</dt><dd className="num">{fmtP(r.p_slope)}</dd></div>
                    {ok.log_x && ok.log_y && <p className="pt-1 text-xs text-muted">Em log-log, a inclinação é uma elasticidade: +1% em X associa-se a {fmtNum(r.slope, 2)}% em Y.</p>}
                  </dl>
                ) : <p className="text-sm text-muted">Amostra insuficiente.</p>}
              </Card>
            </div>
            <Notice kind="warn">{ok.warning} Erros-padrão não consideram heterocedasticidade nem autocorrelação espacial.</Notice>
            {ok.notes.map((n) => <Notice key={n}>{n}</Notice>)}
            <div className="grid gap-4 md:grid-cols-2"><Provenance meta={ok.x} period={ok.period_x} /><Provenance meta={ok.y} period={ok.period_y} /></div>
          </>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Distribuição e desigualdade
type DistResp = {
  meta: VarMeta; level: string; period: string; stats: Stats; log: boolean; weight_note: string | null; inequality_note: string; n_missing: number; dropped_nonpositive_log: number;
  inequality: { n: number; gini: number | null; theil: number | null; cv?: number | null; p90_p10?: number | null; max_min?: number | null };
  histogram: { lo: number; hi: number; n: number }[];
};

function Distribution() {
  const [spec, setSpec] = useState("pib_per_capita");
  const [level, setLevel] = useState("MUN");
  const [uf, setUf] = useState("");
  const [real, setReal] = useState(false);
  const [log, setLog] = useState(true);
  const [wp, setWp] = useState(false);
  const { periods, period, setPeriod } = usePeriod(spec, level);
  const { data, error, loading } = useApi<DistResp>(period ? `/api/lab/distribution${qs({ var: spec, level, period, real, uf, log, weight_pop: wp })}` : null);
  const ok = data && data.meta.spec === spec ? data : null;
  const build = useCallback((t: Theme) => {
    if (!ok) return {};
    return {
      ...baseOption(t), legend: { show: false },
      tooltip: { ...(baseOption(t).tooltip as object), formatter: (p: unknown) => { const h = ok.histogram[(p as { dataIndex: number }).dataIndex]; return `${fmtValue(h.lo, ok.meta, { unit: false })} a ${fmtValue(h.hi, ok.meta)}<br/><b>${h.n}</b> territórios`; } },
      xAxis: { type: "category", data: ok.histogram.map((h) => axisFmt(h.lo)), name: `${ok.meta.unit}${ok.log ? " (classes em escala log)" : ""}`, nameLocation: "middle", nameGap: 26, ...axis(t, { splitLine: { show: false } }) },
      yAxis: { type: "value", name: "territórios", ...axis(t) },
      grid: { left: 8, right: 16, top: 28, bottom: 30, containLabel: true },
      series: [{ type: "bar", data: ok.histogram.map((h) => h.n), barCategoryGap: "4%", itemStyle: { color: t.accent } }],
    };
  }, [ok]);
  const iq = ok?.inequality;
  return (
    <div className="grid gap-5 xl:grid-cols-[21rem_1fr]">
      <Card title="Seleção">
        <div className="space-y-3">
          <Field label="Indicador"><IndicatorSelect value={spec} onChange={setSpec} level={level} frequency="A" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Nível"><Select value={level} onChange={setLevel} options={LEVEL_OPTIONS} /></Field>
            <Field label="Período"><PeriodSelect value={period} onChange={setPeriod} periods={periods} /></Field>
          </div>
          <Field label="Recorte"><UfSelect value={uf} onChange={setUf} /></Field>
          <Check checked={log} onChange={setLog} label="Histograma em escala logarítmica" />
          <Check checked={wp} onChange={setWp} label="Ponderar desigualdade pela população" />
          <Check checked={real} onChange={setReal} label="Valores monetários reais (IPCA)" />
        </div>
      </Card>
      <div className="space-y-4">
        {error && <Notice kind="error">{error}</Notice>}
        {loading && !ok && <Loading />}
        {ok && iq && (
          <>
            <Card title={`Distribuição de ${ok.meta.name} — ${LEVEL_NAMES[ok.level]}, ${periodLabel(ok.period)}`}>
              <Chart build={build} height={340} renderer="svg" exportName="atlas_distribuicao" ariaLabel="Histograma" />
              {ok.dropped_nonpositive_log > 0 && <p className="text-xs text-warn">{ok.dropped_nonpositive_log} territórios com valor ≤ 0 não aparecem no histograma logarítmico.</p>}
            </Card>
            <div className="grid grid-cols-2 gap-4 rounded-md border border-line bg-surface p-4 md:grid-cols-4">
              <Stat label="Territórios (n)" value={fmtNum(ok.stats.n, 0)} sub={`${ok.n_missing} sem dado`} />
              <Stat label="Mediana" value={fmtValue(ok.stats.median, ok.meta)} />
              <Stat label="Média simples" value={fmtValue(ok.stats.mean, ok.meta)} />
              <Stat label="Desvio-padrão" value={fmtValue(ok.stats.std, ok.meta, { unit: false })} />
              <Stat label="P10" value={fmtValue(ok.stats.p10, ok.meta, { unit: false })} />
              <Stat label="P25 – P75" value={`${fmtValue(ok.stats.p25, ok.meta, { unit: false })} – ${fmtValue(ok.stats.p75, ok.meta, { unit: false })}`} />
              <Stat label="P90" value={fmtValue(ok.stats.p90, ok.meta, { unit: false })} />
              <Stat label="Mín. – máx." value={`${fmtValue(ok.stats.min, ok.meta, { unit: false })} – ${fmtValue(ok.stats.max, ok.meta, { unit: false })}`} />
            </div>
            <Card title="Desigualdade territorial">
              <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
                <Stat label="Gini" value={fmtNum(iq.gini, 3)} />
                <Stat label="Theil-T" value={fmtNum(iq.theil, 3)} />
                <Stat label="Coef. de variação" value={fmtNum(iq.cv, 2)} />
                <Stat label="Razão P90/P10" value={fmtNum(iq.p90_p10, 2)} />
                <Stat label="Razão máx./mín." value={fmtNum(iq.max_min, 1)} />
              </div>
              <p className="mt-3 text-xs leading-relaxed text-muted">{ok.inequality_note} {ok.weight_note ?? "Sem ponderação: cada território pesa igualmente, qualquer que seja sua população."} Estas medidas descrevem diferenças entre territórios, não entre pessoas.</p>
            </Card>
            <Provenance meta={ok.meta} period={periodLabel(ok.period)} />
          </>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Ranking
type RankResp = { meta: VarMeta; level: string; period: string; n_ranked: number; n_missing: number; rows: { rank: number; code: string; name: string; uf: string | null; value: number }[] };

function Ranking() {
  const sp = useSearchParams();
  const [spec, setSpec] = useState(sp.get("var") ?? "icr");
  const [level, setLevel] = useState("MUN");
  const [uf, setUf] = useState("");
  const [real, setReal] = useState(false);
  const [order, setOrder] = useState("desc");
  const [n, setN] = useState("50");
  const [popMin, setPopMin] = useState("");
  const { periods, period, setPeriod } = usePeriod(spec, level);
  const { data, error, loading } = useApi<RankResp>(period ? `/api/lab/ranking${qs({ var: spec, level, period, real, uf, n, order, pop_min: popMin })}` : null);
  const ok = data && data.meta.spec === spec ? data : null;
  return (
    <div className="grid gap-5 xl:grid-cols-[21rem_1fr]">
      <Card title="Seleção">
        <div className="space-y-3">
          <Field label="Indicador"><IndicatorSelect value={spec} onChange={setSpec} level={level} frequency="A" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Nível"><Select value={level} onChange={setLevel} options={LEVEL_OPTIONS} /></Field>
            <Field label="Período"><PeriodSelect value={period} onChange={setPeriod} periods={periods} /></Field>
            <Field label="Ordem"><Select value={order} onChange={setOrder} options={[{ value: "desc", label: "Maiores" }, { value: "asc", label: "Menores" }]} /></Field>
            <Field label="Linhas"><Select value={n} onChange={setN} options={["20", "50", "100", "500", "6000"].map((v) => ({ value: v, label: v === "6000" ? "Todas" : v }))} /></Field>
          </div>
          <Field label="Recorte"><UfSelect value={uf} onChange={setUf} /></Field>
          <Field label="População mínima"><input className={inputCls} inputMode="numeric" value={popMin} onChange={(e) => setPopMin(e.target.value.replace(/\D/g, ""))} placeholder="ex.: 100000" /></Field>
          <Check checked={real} onChange={setReal} label="Valores monetários reais (IPCA)" />
        </div>
      </Card>
      <div className="space-y-4">
        {error && <Notice kind="error">{error}</Notice>}
        {loading && !ok && <Loading />}
        {ok && (
          <Card title={`${ok.meta.name} — ${periodLabel(ok.period)}`} actions={
            <a className="rounded border border-line px-3 py-1.5 text-sm hover:border-muted" href={`${API}/api/export${qs({ vars: spec, level, periods: ok.period, real, uf, format: "csv" })}`}>Exportar todos (CSV)</a>}>
            <p className="mb-2 text-xs text-muted">{fmtNum(ok.n_ranked, 0)} territórios com dado; {ok.n_missing} sem dado ficam fora do ranking.</p>
            <div className="max-h-[560px] overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-1.5 pr-3">#</th><th className="px-3 py-1.5">Território</th><th className="py-1.5 pl-3 text-right">{ok.meta.unit}</th></tr></thead>
                <tbody>{ok.rows.map((r) => (
                  <tr key={r.code} className="border-t border-line"><td className="num py-1 pr-3 text-muted">{r.rank}</td>
                    <td className="px-3 py-1"><Link className="hover:text-accent hover:underline" href={`/territorios/${r.code}`}>{r.name}{r.uf ? ` (${r.uf})` : ""}</Link></td>
                    <td className="num py-1 pl-3 text-right">{fmtValue(r.value, ok.meta, { unit: false })}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <div className="mt-3"><Provenance meta={ok.meta} period={periodLabel(ok.period)} /></div>
          </Card>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Grupos territoriais
type GroupResp = { meta: VarMeta; level: string; period: string; by: string; note: string; groups: (Stats & { code: string; name: string; n_missing: number; aggregate_value: number | null })[] };

function Groups() {
  const [spec, setSpec] = useState("icr");
  const [level, setLevel] = useState("MUN");
  const [by, setBy] = useState("regiao");
  const [real, setReal] = useState(false);
  const { periods, period, setPeriod } = usePeriod(spec, level);
  const byOk = level === "UF" ? "regiao" : by;
  const { data, error, loading } = useApi<GroupResp>(period ? `/api/lab/groups${qs({ var: spec, level, period, real, by: byOk })}` : null);
  const ok = data && data.meta.spec === spec ? data : null;
  const build = useCallback((t: Theme) => {
    if (!ok) return {};
    const g = ok.groups.filter((x) => x.n > 0);
    return {
      ...baseOption(t), legend: { show: false },
      tooltip: { ...(baseOption(t).tooltip as object), trigger: "item", formatter: (p: unknown) => {
        const x = g[(p as { dataIndex: number }).dataIndex];
        return `<b>${x.name}</b> (n = ${x.n})<br/>P10: ${fmtValue(x.p10, ok.meta)}<br/>P25: ${fmtValue(x.p25, ok.meta)}<br/>Mediana: ${fmtValue(x.median, ok.meta)}<br/>P75: ${fmtValue(x.p75, ok.meta)}<br/>P90: ${fmtValue(x.p90, ok.meta)}`;
      } },
      xAxis: { type: "category", data: g.map((x) => x.name), ...axis(t, { axisLabel: { color: t.muted, fontSize: 11, rotate: g.length > 8 ? 50 : 0, interval: 0 }, splitLine: { show: false } }) },
      yAxis: { type: "value", scale: true, name: ok.meta.unit, ...axis(t, { axisLabel: { color: t.muted, formatter: (v: number) => axisFmt(v) } }) },
      series: [{ type: "boxplot", data: g.map((x) => [x.p10, x.p25, x.median, x.p75, x.p90]), itemStyle: { color: t.surface, borderColor: t.accent, borderWidth: 1.5 } }],
    };
  }, [ok]);
  return (
    <div className="grid gap-5 xl:grid-cols-[21rem_1fr]">
      <Card title="Seleção">
        <div className="space-y-3">
          <Field label="Indicador"><IndicatorSelect value={spec} onChange={setSpec} level={level} frequency="A" /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Unidades"><Select value={level} onChange={setLevel} options={LVL_NO_REGIAO} /></Field>
            <Field label="Período"><PeriodSelect value={period} onChange={setPeriod} periods={periods} /></Field>
          </div>
          <Field label="Agrupar por"><Select value={byOk} onChange={setBy} options={[{ value: "regiao", label: "Grande região" }, ...(level === "UF" ? [] : [{ value: "uf", label: "Unidade da Federação" }])]} /></Field>
          <Check checked={real} onChange={setReal} label="Valores monetários reais (IPCA)" />
        </div>
      </Card>
      <div className="space-y-4">
        {error && <Notice kind="error">{error}</Notice>}
        {loading && !ok && <Loading />}
        {ok && (
          <Card title={`${ok.meta.name} por ${ok.by === "regiao" ? "grande região" : "UF"} — ${LEVEL_NAMES[ok.level].toLowerCase()}, ${periodLabel(ok.period)}`}>
            <Chart build={build} height={360} renderer="svg" exportName="atlas_grupos" ariaLabel="Distribuição por grupo territorial" />
            <p className="text-xs text-muted">Caixas: P25–P75 com a mediana; hastes: P10 e P90 dos {LEVEL_NAMES[ok.level].toLowerCase()} de cada grupo.</p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full min-w-[620px] text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-1.5 pr-3">Grupo</th><th className="px-3 py-1.5 text-right">n</th><th className="px-3 py-1.5 text-right">Sem dado</th><th className="px-3 py-1.5 text-right">Mediana</th><th className="px-3 py-1.5 text-right">Média simples</th><th className="py-1.5 pl-3 text-right">Valor do agregado</th></tr></thead>
                <tbody>{ok.groups.map((g) => (
                  <tr key={g.code} className="border-t border-line"><td className="py-1 pr-3"><Link className="hover:text-accent hover:underline" href={`/territorios/${g.code}`}>{g.name}</Link></td>
                    <td className="num px-3 py-1 text-right">{g.n}</td><td className="num px-3 py-1 text-right text-muted">{g.n_missing}</td>
                    <td className="num px-3 py-1 text-right">{fmtValue(g.median, ok.meta, { unit: false })}</td><td className="num px-3 py-1 text-right">{fmtValue(g.mean, ok.meta, { unit: false })}</td>
                    <td className="num py-1 pl-3 text-right">{fmtValue(g.aggregate_value, ok.meta, { unit: false })}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <p className="mt-2 text-xs leading-relaxed text-muted">{ok.note}</p>
            <div className="mt-3"><Provenance meta={ok.meta} period={periodLabel(ok.period)} /></div>
          </Card>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Construtor de indicadores
type FormulaResp = { valid: boolean; error?: string; spec?: string; unit?: string; periods?: string[]; references?: { id: string; name: string; unit: string }[]; preview_period?: string; stats?: Stats; div_zero?: number; n_missing?: number; warning?: string };
const EXAMPLES = [
  ["Crédito / Depósitos (%)", "pct(credito_total, depositos_total)"],
  ["Crédito / PIB (%)", "pct(credito_total, pib_nominal)"],
  ["Depósitos por habitante", "depositos_total / populacao"],
  ["VAB industrial por habitante", "vab_industria / populacao"],
  ["Impostos sobre produtos / PIB (%)", "pct(impostos_produtos, pib_nominal)"],
  ["Crescimento real do PIB em 10 anos (%)", "var(real(pib_nominal), 10)"],
  ["Variação % do crédito em 5 anos", "var(credito_total, 5)"],
  ["Poupança por domicílio", "depositos_poupanca / ultimo(domicilios_total)"],
];

function Builder() {
  const { indicators, custom } = useCatalog();
  const [expr, setExpr] = useState("pct(credito_total, pib_nominal)");
  const [name, setName] = useState("");
  const [level, setLevel] = useState("MUN");
  const [res, setRes] = useState<FormulaResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("");
  useEffect(() => {
    if (!expr.trim()) return;
    const t = setTimeout(() => {
      setBusy(true);
      post<FormulaResp>("/api/lab/formula", { expr, level }).then(setRes).catch((e: Error) => setRes({ valid: false, error: e.message })).finally(() => setBusy(false));
    }, 350);
    return () => clearTimeout(t);
  }, [expr, level]);
  const usable = indicators.filter((i) => i.status === "disponivel" && i.frequency === "A" && i.levels.includes(level) && (!filter || (i.name + i.id).toLowerCase().includes(filter.toLowerCase())));
  const save = () => {
    if (!res?.valid || !name.trim()) return;
    saveCustom([...getCustom().filter((c) => c.expr !== expr), { name: name.trim(), expr }]);
    setName("");
  };
  const shown = expr.trim() ? res : null;
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_22rem]">
      <div className="space-y-4">
        <Card title="Editor de fórmulas">
          <Field label="Fórmula" hint="Use os identificadores dos indicadores (lista ao lado), números, + − × ÷ (* /), ** e parênteses.">
            <textarea className={`${inputCls} num min-h-24`} value={expr} onChange={(e) => setExpr(e.target.value)} spellCheck={false} aria-describedby="formula-status" />
          </Field>
          <div className="mt-3 grid gap-3 sm:grid-cols-[12rem_1fr_auto] sm:items-end">
            <Field label="Nível territorial"><Select value={level} onChange={setLevel} options={LEVEL_OPTIONS} /></Field>
            <Field label="Nome do indicador"><input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="ex.: Crédito sobre PIB" maxLength={80} /></Field>
            <Button variant="primary" onClick={save} disabled={!shown?.valid || !name.trim()}>Salvar indicador</Button>
          </div>
          <div id="formula-status" className="mt-4" aria-live="polite">
            {!expr.trim() && <Notice>Digite uma fórmula ou escolha um exemplo.</Notice>}
            {busy && !shown && <Loading label="Validando…" />}
            {shown && !shown.valid && <Notice kind="error"><strong>Fórmula inválida.</strong> {shown.error}</Notice>}
            {shown?.valid && (
              <div className="space-y-3">
                <Notice><strong className="text-ink">Fórmula válida.</strong> Unidade resultante: <strong className="text-ink">{shown.unit}</strong>. {shown.warning}</Notice>
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <Stat label="Períodos com dados" value={shown.periods?.length ? `${shown.periods[0]}–${shown.periods[shown.periods.length - 1]}` : "nenhum"} sub={`${shown.periods?.length ?? 0} períodos`} />
                  {shown.stats && <Stat label={`Territórios (${shown.preview_period})`} value={fmtNum(shown.stats.n, 0)} sub={`${shown.n_missing} sem dado`} />}
                  {shown.stats?.median !== undefined && <Stat label="Mediana" value={fmtNum(shown.stats.median, 2)} sub={shown.unit} />}
                  <Stat label="Divisões por zero" value={String(shown.div_zero ?? 0)} sub="tratadas como ausentes" />
                </div>
                <div className="flex flex-wrap gap-2 text-sm">
                  <Link className="rounded border border-line px-3 py-1.5 hover:border-accent" href={`/atlas${qs({ var: shown.spec, level })}`}>Ver no mapa</Link>
                  <Link className="rounded border border-line px-3 py-1.5 hover:border-accent" href={`/series${qs({ var: shown.spec })}`}>Série histórica</Link>
                  <a className="rounded border border-line px-3 py-1.5 hover:border-accent" href={`${API}/api/export${qs({ vars: shown.spec, level, periods: shown.preview_period, format: "csv" })}`}>Exportar CSV</a>
                </div>
                <p className="text-xs text-muted">Componentes: {shown.references?.map((r) => `${r.name} (${r.unit})`).join("; ")}. Indicadores personalizados são identificados como tal em mapas, gráficos e exportações.</p>
              </div>
            )}
          </div>
        </Card>
        <Card title="Regras e funções">
          <ul className="space-y-1.5 text-sm">
            <li><code className="num">pct(a, b)</code> — a ÷ b × 100; exige a mesma unidade em a e b.</li>
            <li><code className="num">part(a, b)</code> — como pct, para a participação de uma parte no todo: resultados fora de 0–100% (parte negativa ou maior que o total na fonte) ficam ausentes.</li>
            <li><code className="num">var(x, n)</code> — variação % em relação a n períodos antes; <code className="num">var(real(x), n)</code> para variação real.</li>
            <li><code className="num">lag(x, n)</code> — valor de x defasado em n períodos.</li>
            <li><code className="num">real(x)</code> — deflaciona um valor monetário nominal pelo IPCA.</li>
            <li><code className="num">ultimo(x)</code> — último valor disponível de x (para denominadores censitários).</li>
            <li><code className="num">log(x)</code> — logaritmo natural (ausente para valores ≤ 0).</li>
          </ul>
          <p className="mt-3 text-xs leading-relaxed text-muted">Soma e subtração exigem unidades iguais (R$ + pessoas é rejeitado). Divisão por zero e operandos ausentes produzem valor ausente — nunca zero ou infinito. Indicadores anuais e mensais não são combinados.</p>
        </Card>
        {custom.length > 0 && (
          <Card title="Indicadores salvos neste navegador">
            <ul className="text-sm">{custom.map((c) => (
              <li key={c.expr} className="flex flex-wrap items-baseline justify-between gap-2 border-b border-line py-1.5">
                <span><span className="font-medium">{c.name}</span> <code className="num text-xs text-muted">{c.expr}</code></span>
                <span className="flex gap-3"><button type="button" className="text-accent underline" onClick={() => setExpr(c.expr)}>Editar</button>
                  <button type="button" className="text-muted hover:text-danger" onClick={() => saveCustom(getCustom().filter((x) => x.expr !== c.expr))}>Excluir</button></span>
              </li>
            ))}</ul>
          </Card>
        )}
      </div>
      <aside className="space-y-4">
        <Card title="Exemplos">
          <ul className="space-y-1 text-sm">{EXAMPLES.map(([n, e]) => <li key={e}><button type="button" className="text-left hover:text-accent" onClick={() => { setExpr(e); setName(n); }}>{n}<span className="num block text-xs text-muted">{e}</span></button></li>)}</ul>
        </Card>
        <Card title="Indicadores disponíveis">
          <input className={`${inputCls} mb-2`} placeholder="Filtrar…" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filtrar indicadores" />
          <ul className="max-h-96 overflow-auto text-sm">{usable.map((i) => (
            <li key={i.id}><button type="button" title="Inserir na fórmula" onClick={() => setExpr((s) => (s.trim() ? s + " " : "") + i.id)} className="w-full border-b border-line py-1 text-left hover:text-accent">
              <span className="num text-xs">{i.id}</span><span className="block text-xs text-muted">{i.name} · {i.unit}</span></button></li>
          ))}</ul>
        </Card>
      </aside>
    </div>
  );
}

// ------------------------------------------------------------------ Pesquisa avançada
type Cond = { var: string; op: string; mode: string; value: string; value2: string; real: boolean };
type SearchResp = {
  level: string; n_scope: number; n_match: number; n_excluded_missing: number; truncated: boolean;
  conditions: { meta: VarMeta; period: string; op: string; threshold: number; threshold2: number | null; ref: string | null }[];
  rows: { code: string; name: string; uf: string | null; values: (number | null)[] }[];
};
const OPS = [{ value: ">", label: "maior que" }, { value: ">=", label: "maior ou igual a" }, { value: "<", label: "menor que" }, { value: "<=", label: "menor ou igual a" }, { value: "entre", label: "entre" }];
const MODES = [{ value: "valor", label: "um valor" }, { value: "mediana", label: "a mediana dos territórios" }, { value: "media", label: "a média dos territórios" }, { value: "br", label: "o valor do Brasil" }];
const START: Cond[] = [
  { var: "=var(real(pib_nominal), 10)", op: ">", mode: "br", value: "", value2: "", real: false },
  { var: "credito_pc", op: "<", mode: "mediana", value: "", value2: "", real: false },
  { var: "populacao", op: ">", mode: "valor", value: "50000", value2: "", real: false },
];

function Search() {
  const [level, setLevel] = useState("MUN");
  const [uf, setUf] = useState("");
  const [conds, setConds] = useState<Cond[]>(START);
  const [period, setPeriod] = useState("2021");
  const [body, setBody] = useState<unknown>(null);
  const { data, error, loading } = useApi<SearchResp>(body ? "/api/lab/search" : null, body ?? undefined);
  const upd = (i: number, p: Partial<Cond>) => setConds(conds.map((c, j) => (j === i ? { ...c, ...p } : c)));
  const run = () => setBody({
    level, uf: uf || null, limit: 500,
    conditions: conds.map((c) => ({ var: c.var, op: c.op, period: period || null, real: c.real, ref: c.mode === "valor" || c.op === "entre" ? null : c.mode,
      value: c.mode === "valor" || c.op === "entre" ? Number(c.value.replace(",", ".")) : null, value2: c.op === "entre" ? Number(c.value2.replace(",", ".")) : null })),
  });
  const invalid = conds.some((c) => (c.mode === "valor" || c.op === "entre") && (c.value.trim() === "" || Number.isNaN(Number(c.value.replace(",", ".")))));
  const csv = () => {
    if (!data) return;
    const head = ["# Atlas Econômico e Social do Brasil — pesquisa avançada", ...data.conditions.map((c, i) => `# Condição ${i + 1}: ${c.meta.name} (${c.meta.unit}, ${c.period}) ${c.op} ${c.threshold}${c.ref ? " [" + c.ref + "]" : ""}`),
      ["codigo_ibge", "territorio", "uf", ...data.conditions.map((c) => `"${c.meta.name} (${c.period})"`)].join(",")];
    download("atlas_pesquisa.csv", "﻿" + head.concat(data.rows.map((r) => [r.code, `"${r.name}"`, r.uf ?? "", ...r.values.map((v) => v ?? "")].join(","))).join("\n"), "text/csv");
  };
  return (
    <div className="space-y-5">
      <Card title="Condições (todas devem ser satisfeitas)">
        <div className="mb-4 grid gap-3 sm:grid-cols-3 lg:max-w-3xl">
          <Field label="Nível territorial"><Select value={level} onChange={setLevel} options={LEVEL_OPTIONS} /></Field>
          <Field label="Recorte"><UfSelect value={uf} onChange={setUf} /></Field>
          <Field label="Ano de referência" hint="Vazio = último ano de cada indicador."><input className={inputCls} inputMode="numeric" value={period} onChange={(e) => setPeriod(e.target.value.replace(/\D/g, "").slice(0, 4))} /></Field>
        </div>
        <ol className="space-y-3">
          {conds.map((c, i) => (
            <li key={i} className="grid gap-2 rounded border border-line p-3 md:grid-cols-[1.6fr_11rem_13rem_1fr_auto] md:items-end">
              <Field label={`Condição ${i + 1}`}><IndicatorSelect value={c.var} onChange={(v) => upd(i, { var: v })} level={level} frequency="A" /></Field>
              <Field label="Operador"><Select value={c.op} onChange={(op) => upd(i, { op })} options={OPS} /></Field>
              <Field label="Comparar com"><Select value={c.op === "entre" ? "valor" : c.mode} onChange={(mode) => upd(i, { mode })} options={MODES} disabled={c.op === "entre"} /></Field>
              <div className="flex gap-2">
                {(c.mode === "valor" || c.op === "entre") && <Field label={c.op === "entre" ? "Mínimo" : "Valor"}><input className={inputCls} value={c.value} onChange={(e) => upd(i, { value: e.target.value })} inputMode="decimal" /></Field>}
                {c.op === "entre" && <Field label="Máximo"><input className={inputCls} value={c.value2} onChange={(e) => upd(i, { value2: e.target.value })} inputMode="decimal" /></Field>}
              </div>
              <button type="button" className="pb-1.5 text-sm text-muted hover:text-danger" onClick={() => setConds(conds.filter((_, j) => j !== i))} disabled={conds.length === 1}>Remover</button>
            </li>
          ))}
        </ol>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => conds.length < 8 && setConds([...conds, { var: "pib_per_capita", op: ">", mode: "mediana", value: "", value2: "", real: false }])}>Adicionar condição</Button>
          <Button variant="primary" onClick={run} disabled={invalid}>Pesquisar</Button>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">O exemplo inicial busca municípios com crescimento real do PIB em dez anos acima do nacional, crédito per capita abaixo da mediana e mais de 50 mil habitantes. Crie indicadores no Construtor para usá-los aqui.</p>
      </Card>
      {error && <Notice kind="error">{error}</Notice>}
      {loading && <Loading />}
      {data && !loading && (
        <Card title={`${fmtNum(data.n_match, 0)} territórios atendem a todas as condições`} actions={<Button onClick={csv}>Exportar CSV</Button>}>
          <div className="mb-3 grid gap-4 sm:grid-cols-3">
            <Stat label="Territórios no recorte" value={fmtNum(data.n_scope, 0)} />
            <Stat label="Atendem às condições" value={fmtNum(data.n_match, 0)} />
            <Stat label="Não avaliados (dado ausente)" value={fmtNum(data.n_excluded_missing, 0)} sub="sem dado em ao menos uma condição" />
          </div>
          <ul className="mb-3 space-y-0.5 text-xs text-muted">{data.conditions.map((c, i) => (
            <li key={i}>Condição {i + 1}: {c.meta.name} ({periodLabel(c.period)}) {OPS.find((o) => o.value === c.op)?.label} <span className="num">{fmtValue(c.threshold, c.meta)}</span>{c.threshold2 !== null ? <> e <span className="num">{fmtValue(c.threshold2, c.meta)}</span></> : null}{c.ref ? ` — ${c.ref}` : ""}{c.meta.notes.length ? ` · ${c.meta.notes.join(" ")}` : ""}</li>
          ))}</ul>
          <div className="max-h-[520px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-surface text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-1.5 pr-3">Território</th>{data.conditions.map((c, i) => <th key={i} className="px-3 py-1.5 text-right">{c.meta.short_name.replace("Indicador personalizado: ", "")}</th>)}</tr></thead>
              <tbody>{data.rows.map((r) => (
                <tr key={r.code} className="border-t border-line"><td className="py-1 pr-3"><Link className="hover:text-accent hover:underline" href={`/territorios/${r.code}`}>{r.name}{r.uf ? ` (${r.uf})` : ""}</Link></td>
                  {r.values.map((v, i) => <td key={i} className="num px-3 py-1 text-right">{fmtValue(v, data.conditions[i].meta, { unit: false })}</td>)}</tr>
              ))}</tbody>
            </table>
          </div>
          {data.truncated && <p className="mt-2 text-xs text-muted">Exibindo os primeiros {data.rows.length} resultados.</p>}
        </Card>
      )}
    </div>
  );
}

const TABS = [
  { id: "dispersao", label: "Dispersão e correlação" }, { id: "distribuicao", label: "Distribuição e desigualdade" }, { id: "ranking", label: "Rankings" },
  { id: "grupos", label: "Grupos territoriais" }, { id: "construtor", label: "Construtor de indicadores" }, { id: "pesquisa", label: "Pesquisa avançada" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export default function LabView() {
  const sp = useSearchParams();
  const initial = TABS.find((t) => t.id === sp.get("tab"))?.id ?? "dispersao";
  const [tab, setTab] = useState<TabId>(initial);
  return (
    <Page wide title="Laboratório Econômico" lead="Cruze indicadores, meça associações e desigualdades territoriais e construa seus próprios indicadores — sem programar. Toda análise informa tamanho amostral, período, dados ausentes e limitações.">
      <Tabs value={tab} onChange={setTab} tabs={[...TABS]} />
      <div className="mt-5">
        {tab === "dispersao" && <Scatter />}
        {tab === "distribuicao" && <Distribution />}
        {tab === "ranking" && <Ranking />}
        {tab === "grupos" && <Groups />}
        {tab === "construtor" && <Builder />}
        {tab === "pesquisa" && <Search />}
      </div>
    </Page>
  );
}
