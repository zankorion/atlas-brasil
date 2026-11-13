import type { EChartsOption } from "echarts";
import { axis, baseOption, type Theme } from "@/components/Chart";
import type { VarMeta } from "./api";
import { axisFmt, fmtNum, fmtValue, periodLabel } from "./format";

export type Serie = { code: string; name: string; level: string; uf: string | null; points: { period: string; value: number | null }[] };
export type Transform = "nivel" | "indice" | "variacao";

export function serieLabel(s: Serie): string {
  return s.uf && s.level === "MUN" ? `${s.name} (${s.uf})` : s.name;
}

/** Aplica a transformação escolhida; ausências permanecem ausências. */
export function transformSeries(series: Serie[], transform: Transform, periods: string[]): { rows: (number | null)[][]; base: string | null } {
  const maps = series.map((s) => new Map(s.points.map((p) => [p.period, p.value])));
  if (transform === "nivel") return { rows: maps.map((m) => periods.map((p) => m.get(p) ?? null)), base: null };
  if (transform === "indice") {
    // Base 100 no primeiro período em que TODAS as séries têm valor.
    const base = periods.find((p) => maps.every((m) => m.get(p) !== null && m.get(p) !== undefined && m.get(p) !== 0)) ?? null;
    return {
      rows: maps.map((m) => periods.map((p) => {
        const v = m.get(p), b = base ? m.get(base) : null;
        return v === null || v === undefined || !b ? null : (v / b) * 100;
      })),
      base,
    };
  }
  const step = periods[0]?.includes("-") ? 12 : 1; // variação sobre o mesmo período do ano anterior
  return {
    rows: maps.map((m) => periods.map((p, i) => {
      const prevP = step === 1 ? String(Number(p) - 1) : `${Number(p.slice(0, 4)) - 1}${p.slice(4)}`;
      const v = m.get(p), prev = m.get(prevP);
      void i;
      return v === null || v === undefined || prev === null || prev === undefined || prev === 0 ? null : (v / prev - 1) * 100;
    })),
    base: null,
  };
}

export function allPeriods(series: Serie[]): string[] {
  return [...new Set(series.flatMap((s) => s.points.map((p) => p.period)))].sort();
}

export function lineOption(t: Theme, series: Serie[], meta: VarMeta, transform: Transform, marks: { period: string; label: string }[] = []): EChartsOption {
  const periods = allPeriods(series);
  const { rows } = transformSeries(series, transform, periods);
  const unit = transform === "nivel" ? meta : { unit: transform === "indice" ? "índice" : "%", decimals: 1 };
  const monthly = periods[0]?.includes("-");
  return {
    ...baseOption(t),
    tooltip: {
      ...(baseOption(t).tooltip as object), trigger: "axis",
      formatter: (ps: unknown) => {
        const arr = ps as { axisValue: string; marker: string; seriesName: string; value: number | null }[];
        const lines = arr.map((p) => `${p.marker} ${p.seriesName}: <b>${p.value === null || p.value === undefined ? "sem dado" : fmtValue(p.value, unit)}</b>`);
        return `<div style="font-weight:600;margin-bottom:2px">${periodLabel(arr[0].axisValue)}</div>${lines.join("<br/>")}`;
      },
    },
    xAxis: { type: "category", data: periods, boundaryGap: false,
      ...axis(t, { axisLabel: { color: t.muted, fontSize: 11, formatter: (v: string) => (monthly ? (v.endsWith("-01") ? v.slice(0, 4) : "") : v), interval: monthly ? 0 : "auto" }, splitLine: { show: false } }) },
    yAxis: { type: "value", scale: true, ...axis(t, { axisLabel: { color: t.muted, fontSize: 11, formatter: (v: number) => axisFmt(v) } }) },
    series: series.map((s, i) => ({
      name: serieLabel(s), type: "line", data: rows[i], connectNulls: false, showSymbol: !monthly && periods.length < 40, symbolSize: 5,
      lineStyle: { width: 2 },
      markLine: i === 0 && marks.length ? {
        symbol: "none", silent: true, lineStyle: { color: t.muted, type: "dashed", width: 1 },
        label: { color: t.muted, fontSize: 10, formatter: (p: { name?: string }) => p.name ?? "" },
        data: marks.filter((m) => periods.includes(m.period)).map((m) => ({ xAxis: m.period, name: m.label })),
      } : undefined,
    })),
  };
}

export function quantileBreaks(values: number[], k: number): number[] {
  const a = [...values].sort((x, y) => x - y);
  if (!a.length) return [];
  const out: number[] = [];
  for (let i = 1; i < k; i++) {
    const pos = (a.length - 1) * (i / k), lo = Math.floor(pos), hi = Math.ceil(pos);
    const b = a[lo] + (a[hi] - a[lo]) * (pos - lo);
    if (!out.length || b > out[out.length - 1]) out.push(b);
  }
  return out;
}

export function seriesCsv(series: Serie[], meta: VarMeta, transform: Transform): string {
  const periods = allPeriods(series);
  const { rows, base } = transformSeries(series, transform, periods);
  const head = [
    "# Atlas Econômico e Social do Brasil — série histórica",
    `# Indicador: ${meta.name} (${meta.id ?? meta.spec})`,
    `# Unidade: ${transform === "nivel" ? meta.unit + (meta.real ? " — preços constantes (IPCA)" : "") : transform === "indice" ? `índice (base 100 = ${base})` : "variação % sobre o mesmo período do ano anterior"}`,
    `# Fontes: ${meta.sources.map((s) => `${s.source} — ${s.dataset}${s.updated_at ? ` (carga ${s.updated_at})` : ""}`).join("; ")}`,
    ...(meta.formula ? [`# Fórmula: ${meta.formula}`] : []),
    ...meta.notes.map((n) => `# ${n}`),
    "# Células vazias são valores ausentes — não equivalem a zero.",
  ];
  const lines = [["periodo", ...series.map((s) => `"${serieLabel(s)} [${s.code}]"`)].join(",")];
  periods.forEach((p, j) => lines.push([p, ...rows.map((r) => (r[j] === null ? "" : String(r[j])))].join(",")));
  return "﻿" + head.join("\n") + "\n" + lines.join("\n") + "\n";
}

export { fmtNum };
