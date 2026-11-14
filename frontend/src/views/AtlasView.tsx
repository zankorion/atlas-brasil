"use client";
import { useMoney } from "@/lib/money";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { bboxOf, ChoroMap, type Box } from "@/components/ChoroMap";
import { IndicatorPicker, LEVEL_OPTIONS, TerritorySearch, UfSelect, useCatalog, useUfs } from "@/components/pickers";
import { RankPanel, type RankItem } from "@/components/RankPanel";
import { Button, Field, Notice, Provenance, Select, Stat } from "@/components/ui";
import { API, api, loadGeo, qs, useApi, type MapData, type Stats, type Territory, type Money, type VarMeta } from "@/lib/api";
import { exportPng, exportSvg, type MapExport } from "@/lib/exportMap";
import { download, fmtNum, fmtValue, LEVEL_NAMES, periodLabel, slug } from "@/lib/format";
import { classOf, continuousScale, cssVar, divergingClassColors, PALETTES, ramp, resolvePalette, type ContinuousScale, type ScaleMode } from "@/lib/palettes";
import { ProfileBody } from "./ProfileView";
import { TerritorialCompare } from "./TerritorialCompare";

type Center = "auto" | "nenhum" | "zero" | "br" | "mediana";
type Shared = { level: string; uf: string; real: Money; method: string; scale: ScaleMode; center: Center; k: number; palette: string };
type Sel = { code: string; name: string; level: string; uf?: string | null };
type HistRow = { code: string; name: string; uf: string | null; v0: number | null; v1: number | null; abs: number | null; pct: number | null; cagr: number | null; boundary_change: string[] | null };
type HistResp = { meta: VarMeta; level: string; p0: string; p1: string; years: number; rows: HistRow[]; stats: Stats; n_missing: number; n_boundary_changes: number; method: string | null; breaks: { pct: number[]; abs: number[] } | null };
type UnitLike = { unit: string; decimals?: number };
const PCT: UnitLike = { unit: "%", decimals: 1 };
const PP: UnitLike = { unit: "p.p.", decimals: 2 };
const UF_LEVELS = new Set(["MUN", "RGI", "RGINT"]);  // níveis em que o recorte por UF faz sentido

function describe(a: number[]): Stats {
  if (!a.length) return { n: 0 };
  const s = [...a].sort((x, y) => x - y);
  const q = (p: number) => { const i = (s.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i); return s[lo] + (s[hi] - s[lo]) * (i - lo); };
  return { n: s.length, mean: s.reduce((x, y) => x + y, 0) / s.length, min: s[0], p10: q(0.1), p25: q(0.25), median: q(0.5), p75: q(0.75), p90: q(0.9), max: s[s.length - 1] };
}
const MAX_SEL = 8;

function classLegend(breaks: number[], colors: string[], u: UnitLike, min?: number) {
  const f = (v: number) => fmtValue(v, u, { unit: false });
  if (!breaks.length) return [{ color: colors[colors.length - 1], label: min === undefined ? "—" : f(min) }];
  return colors.slice(0, breaks.length + 1).map((color, i) => ({
    color,
    label: i === 0 ? `até ${f(breaks[0])}` : i === breaks.length ? `acima de ${f(breaks[breaks.length - 1])}` : `${f(breaks[i - 1])} a ${f(breaks[i])}`,
  }));
}

function scaleLegend(sc: ContinuousScale, u: UnitLike) {
  const f = (v: number) => fmtValue(v, u, { unit: false });
  return sc.ticks.map((t, i) => ({
    color: sc.colorOf(t),
    label: i === 0 && sc.clampLo ? `${f(t)} ou menos` : i === sc.ticks.length - 1 && sc.clampHi ? `${f(t)} ou mais` : f(t),
  }));
}

function medianOf(a: number[]): number | null {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y), m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

type PanelProps = {
  shared: Shared; set: (p: Partial<Shared>) => void; initial: string; initialPeriod?: string | null;
  sel: Sel[]; hov: string | null; onHover: (c: string | null) => void; onToggle: (code: string, name: string) => void;
  onSpec?: (spec: string) => void; focusBox: Box | null; outlines: GeoJSON.Feature[];
  /** Selecionados que contêm outro selecionado: não ganham mapa aproximado próprio. */
  containers: Set<string>;
};

function MapPanel({ shared, set, initial, initialPeriod, sel, hov, onHover, onToggle, onSpec, focusBox, outlines, containers }: PanelProps) {
  const [spec, setSpecState] = useState(initial);
  const [period, setPeriod] = useState<string | null>(initialPeriod ?? null);
  const [base, setBase] = useState<string | null>(null);
  const setSpec = (v: string) => { setSpecState(v); setPeriod(null); setBase(null); onSpec?.(v); };
  const continuous = shared.method === "continua";
  const uf = UF_LEVELS.has(shared.level) ? shared.uf : "";
  // Se o indicador não existe no nível territorial escolhido (ex.: SCR só por UF), troca para um que exista.
  const { indicators } = useCatalog();
  const current = indicators.find((i) => i.id === spec);
  const fallback = current && !current.levels.includes(shared.level)
    ? (indicators.find((i) => i.id === "pib_nominal" && i.levels.includes(shared.level)) ?? indicators.find((i) => i.status === "disponivel" && i.frequency === "A" && i.levels.includes(shared.level)))?.id ?? null : null;
  const [switched, setSwitched] = useState<string | null>(null);
  useEffect(() => {
    if (!fallback || !current) return;
    const from = current.short_name;
    const id = requestAnimationFrame(() => { setSwitched(from); setSpecState(fallback); setPeriod(null); setBase(null); });
    return () => cancelAnimationFrame(id);
  }, [fallback, current]);
  // Sem indicador escolhido o mapa fica em branco (só a malha): nada é consultado.
  const { data, error, loading } = useApi<MapData>(
    spec ? `/api/map${qs({ var: spec, level: shared.level, period, real: shared.real, method: continuous ? "quantis" : shared.method, k: shared.k, uf })}` : null,
  );
  const ok = data && data.meta.spec === spec && data.level === shared.level ? data : null;
  const periods = ok?.periods ?? [];
  const cur = ok?.period ?? period;
  const idx = cur ? periods.indexOf(cur) : -1;

  // Modo de variação: compara o período atual com um período-base anterior.
  const baseOk = base && cur && periods.includes(base) && base < cur ? base : null;
  const hist = useApi<HistResp>(baseOk && ok ? `/api/historical${qs({ var: spec, level: shared.level, p0: baseOk, p1: ok.period, real: shared.real, uf, method: continuous ? null : shared.method, k: continuous ? null : shared.k })}` : null);
  const hOk = baseOk && ok && hist.data && hist.data.meta.spec === spec && hist.data.level === shared.level && hist.data.p0 === baseOk && hist.data.p1 === ok.period && (hist.data.method ?? null) === (continuous ? null : shared.method) ? hist.data : null;
  const variation = !!baseOk;
  // Indicadores já expressos em % variam em pontos percentuais (diferença), não em "% de %".
  const inPP = variation && !!ok?.meta.percent;
  const delta = useCallback((r: HistRow) => (inPP ? r.abs : r.pct), [inPP]);
  const unit: UnitLike = variation ? (inPP ? PP : PCT) : ok?.meta ?? PCT;

  const values = useMemo(
    () => (variation ? new Map((hOk?.rows ?? []).map((r) => [r.code, delta(r)])) : new Map((ok?.values ?? []).map((v) => [v.code, v.value]))),
    [variation, hOk, ok, delta],
  );
  const nums = useMemo(() => [...values.values()].filter((v): v is number => v !== null && v !== undefined), [values]);

  // Referência do Brasil para centrar a escala divergente (valor do período ou variação no mesmo intervalo).
  const wantBr = shared.center === "br" || (variation && shared.center === "auto");
  const brMap = useApi<MapData>(!variation && continuous && wantBr && ok ? `/api/map${qs({ var: spec, level: "BR", period: ok.period, real: shared.real })}` : null);
  const brHist = useApi<HistResp>(variation && wantBr && ok ? `/api/historical${qs({ var: spec, level: "BR", p0: baseOk, p1: ok.period, real: shared.real })}` : null);
  const brValue = variation
    ? (brHist.data && ok && brHist.data.meta.spec === spec && brHist.data.p0 === baseOk && brHist.data.p1 === ok.period && brHist.data.rows[0] ? delta(brHist.data.rows[0]) : null)
    : (brMap.data && ok && brMap.data.period === ok.period && brMap.data.meta.spec === spec ? brMap.data.values[0]?.value ?? null : null);

  const { scale, centerLabel } = useMemo(() => {
    // A classificação escolhida vale também na variação entre períodos: a escala contínua só existe no modo contínuo.
    if (!nums.length || !continuous) return { scale: null, centerLabel: null as string | null };
    const crosses = nums.some((v) => v < 0) && nums.some((v) => v > 0);
    let center: number | null = null, label: string | null = null;
    if (shared.center === "zero") [center, label] = [0, "zero"];
    else if (shared.center === "mediana") [center, label] = [medianOf(nums), "mediana dos territórios"];
    else if (shared.center === "br") [center, label] = [brValue, variation ? "variação do Brasil" : "valor do Brasil"];
    else if (shared.center === "auto" && variation) [center, label] = brValue !== null ? [brValue, "variação do Brasil"] : [0, "zero"];
    else if (shared.center === "auto" && crosses) [center, label] = [0, "zero"];
    if (center === null) label = null;
    // A paleta escolhida é sempre usada; só a "Automática" troca para a divergente quando há ponto central.
    return { scale: continuousScale(nums, resolvePalette(shared.palette, center !== null), shared.scale, center), centerLabel: label };
  }, [nums, continuous, variation, shared.center, shared.palette, shared.scale, brValue]);

  const breaks = useMemo(() => (variation ? (inPP ? hOk?.breaks?.abs : hOk?.breaks?.pct) ?? [] : ok?.breaks ?? []), [variation, inPP, hOk, ok]);
  // Em classes, a paleta automática é divergente só quando as classes atravessam o zero (variações positivas e negativas).
  const classCross = breaks.length > 0 && breaks[0] < 0 && breaks[breaks.length - 1] > 0;
  // Nesse caso as cores são alinhadas ao zero (vermelho abaixo, azul acima), e não à classe do meio.
  const colors = useMemo(() => (classCross && shared.palette === "auto" ? divergingClassColors("divergente", breaks) : ramp(resolvePalette(shared.palette, false), breaks.length + 1)),
    [shared.palette, classCross, breaks]);
  const nonPositive = useMemo(() => nums.filter((v) => v <= 0).length, [nums]);
  const colorOf = useCallback(
    (v: number) => (scale ? scale.colorOf(v) : colors[Math.min(colors.length - 1, classOf(v, breaks))]),
    [scale, colors, breaks],
  );
  const nMissing = variation ? (hOk ? hOk.rows.length - nums.length : 0) : ok?.n_missing ?? 0;
  const varStats = useMemo(() => describe(nums), [nums]);
  const stats = variation ? (hOk ? varStats : undefined) : ok?.stats;
  const legend = !ok ? [] : scale ? scaleLegend(scale, unit) : classLegend(breaks, colors, unit, ok.stats.min);
  const legendTitle = ok ? (variation ? `Variação de ${ok.meta.short_name}` : ok.meta.short_name) : "";
  const legendSub = ok ? (variation ? `${inPP ? "pontos percentuais" : "%"} · ${periodLabel(baseOk)} → ${periodLabel(ok.period)}` : `${ok.meta.unit} · ${periodLabel(ok.period)}`) : "";
  const rankOverride = useMemo(() => {
    if (!variation) return null;
    const rows: RankItem[] = (hOk?.rows ?? []).filter((r) => delta(r) !== null).map((r) => ({ code: r.code, name: r.name, uf: r.uf, value: delta(r) as number }));
    return { rows, missing: (hOk?.rows.length ?? 0) - rows.length, title: "Variação" };
  }, [variation, hOk, delta]);
  const selCodes = useMemo(() => sel.map((s) => s.code), [sel]);

  const doExport = async (kind: "png" | "svg") => {
    if (!ok) return;
    const [geo, outline] = await Promise.all([loadGeo(shared.level), shared.level === "UF" || shared.level === "REGIAO" ? null : loadGeo("UF")]);
    const feats = uf ? geo.features.filter((f) => (f.properties as { uf?: string }).uf === uf) : geo.features;
    const missing = "#cbc6ba";
    const o: MapExport = {
      geo: { type: "FeatureCollection", features: feats }, outline,
      colorOf: (code) => {
        const v = values.get(code);
        return v === null || v === undefined ? missing : colorOf(v);
      },
      title: variation ? `${ok.meta.name} — variação ${inPP ? "em pontos percentuais" : "%"}` : ok.meta.name,
      subtitle: `${LEVEL_NAMES[shared.level]} · ${variation ? `${periodLabel(baseOk)} a ${periodLabel(ok.period)}` : `${periodLabel(ok.period)} · ${ok.meta.unit}`}${ok.meta.real || (variation && hOk?.meta.real) ? " (preços constantes, IPCA)" : ""}${scale ? ` · escala contínua ${scale.kind === "log" ? "logarítmica" : "linear"}${centerLabel ? `, centrada em ${centerLabel}` : ""}` : ""}`,
      legend: [...legend, { color: missing, label: `Sem dado (${nMissing})` }],
      source: "Fonte: " + ok.meta.sources.map((s) => `${s.source} — ${s.dataset}`).join("; ").slice(0, 170),
    };
    const name = `atlas_${slug(ok.meta.short_name)}_${variation ? `${baseOk}-` : ""}${ok.period}_${shared.level.toLowerCase()}`;
    if (kind === "svg") exportSvg(o, name, !!uf);
    else await exportPng(o, name, !!uf);
  };
  const exportUrl = (format: string) =>
    `${API}/api/export${qs({ vars: spec, level: shared.level, periods: variation ? `${baseOk},${ok?.period}` : ok?.period, real: shared.real, uf, format })}`;
  const variationCsv = () => {
    if (!hOk || !ok) return;
    const head = ["# Atlas Econômico e Social do Brasil — variação entre dois períodos", `# Indicador: ${hOk.meta.name} (${hOk.meta.unit}${hOk.meta.real ? ", preços constantes (IPCA)" : ""})`,
      `# Períodos: ${hOk.p0} e ${hOk.p1}`, `# Fontes: ${hOk.meta.sources.map((s) => `${s.source} — ${s.dataset}`).join("; ")}`,
      "# Células vazias são valores ausentes — não equivalem a zero. alteracao_territorial = limites mudaram no intervalo.",
      `codigo_ibge,territorio,uf,valor_${hOk.p0},valor_${hOk.p1},diferenca,variacao_pct,pct_ao_ano,alteracao_territorial`];
    download(`atlas_variacao_${slug(ok.meta.short_name)}_${hOk.p0}-${hOk.p1}.csv`, "﻿" + head.concat(hOk.rows.map((r) =>
      [r.code, `"${r.name}"`, r.uf ?? "", r.v0 ?? "", r.v1 ?? "", r.abs ?? "", r.pct ?? "", r.cagr ?? "", r.boundary_change ? "sim" : ""].join(","))).join("\n"), "text/csv");
  };

  return (
    <section aria-label="Mapa" className="flex min-w-0 flex-1 flex-col gap-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_8rem_10rem]">
        <IndicatorPicker value={spec} onChange={setSpec} level={shared.level} frequency="A" />
        <Field label="Período">
          <select className="w-full rounded border border-line bg-surface px-2.5 py-1.5 text-sm" value={cur ?? ""} onChange={(e) => setPeriod(e.target.value)} disabled={!periods.length} aria-label="Período">
            {[...periods].reverse().map((p) => <option key={p} value={p}>{periodLabel(p)}</option>)}
          </select>
        </Field>
        <Field label="Variação desde">
          <select className="w-full rounded border border-line bg-surface px-2.5 py-1.5 text-sm" value={baseOk ?? ""} onChange={(e) => setBase(e.target.value || null)} disabled={periods.length < 2} aria-label="Período-base para calcular a variação">
            <option value="">— (mostrar o valor)</option>
            {periods.filter((p) => !cur || p < cur).reverse().map((p) => <option key={p} value={p}>{periodLabel(p)}</option>)}
          </select>
        </Field>
      </div>
      {periods.length > 1 && (
        <div className="flex items-center gap-3 text-xs text-muted">
          <span className="num">{periods[0]}</span>
          <input type="range" min={0} max={periods.length - 1} step={1} value={Math.max(0, idx)} onChange={(e) => setPeriod(periods[Number(e.target.value)])}
            aria-label="Linha do tempo" aria-valuetext={cur ?? undefined} className="flex-1 accent-[var(--accent)]" />
          <span className="num">{periods[periods.length - 1]}</span>
        </div>
      )}
      {error && !fallback && <Notice kind="error">{error}</Notice>}
      {switched && <Notice>“{switched}” não existe no nível territorial escolhido; o mapa passou a mostrar outro indicador. <button type="button" className="underline" onClick={() => setSwitched(null)}>Entendi</button></Notice>}
      {ok && (ok.n_inconsistent ?? 0) > 0 && (
        <Notice kind="warn">{ok.n_inconsistent} {ok.n_inconsistent === 1 ? "município teve a declaração" : "municípios tiveram a declaração"} de {periodLabel(ok.period)} deixada de fora por inconsistência contábil (por exemplo, receita muitas vezes maior que a despesa) e {ok.n_inconsistent === 1 ? "aparece" : "aparecem"} como “sem dado”. Os valores declarados não são corrigidos; a regra está em Fontes e Metodologia.</Notice>
      )}
      {variation && inPP && <Notice>Este indicador já é uma porcentagem: a variação é mostrada em pontos percentuais (valor final menos valor inicial).</Notice>}
      {variation && hist.error && <Notice kind="error">{hist.error}</Notice>}
      {variation && hOk && hOk.n_boundary_changes > 0 && shared.level === "MUN" && (
        <Notice kind="warn">Entre {hOk.p0} e {hOk.p1}, {hOk.n_boundary_changes} municípios tiveram alteração de limites registrada (instalação ou cessão de área): neles a variação mistura mudança econômica e territorial. Municípios de origem não identificados automaticamente não entram nessa conta.</Notice>
      )}
      {/* Opções de leitura do mapa: ficam junto dele, separadas da escolha de território */}
      <div className="rounded-md border border-line bg-surface p-3">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Field label="Classificação">
            <Select value={shared.method} onChange={(method) => set({ method })} options={[
              { value: "continua", label: "Contínua (gradiente)" }, { value: "jenks", label: "Quebras naturais (Jenks)" }, { value: "quantis", label: "Quantis" },
              { value: "iguais", label: "Intervalos iguais" }, { value: "geometrico", label: "Progressão geométrica" }]} />
          </Field>
          {shared.method === "continua" ? (
            <Field label="Escala">
              <Select value={shared.scale} onChange={(v) => set({ scale: v as ScaleMode })} options={[
                { value: "auto", label: "Automática" }, { value: "linear", label: "Linear" }, { value: "log", label: "Logarítmica" }]} />
            </Field>
          ) : (
            <Field label="Classes">
              <Select value={String(shared.k)} onChange={(k) => set({ k: Number(k) })} options={[3, 4, 5, 6, 7, 8, 9].map((n) => ({ value: String(n), label: String(n) }))} />
            </Field>
          )}
          <Field label="Ponto central" hint={shared.method === "continua" ? undefined : "Só na classificação contínua."}>
            <Select disabled={shared.method !== "continua"} value={shared.center} onChange={(v) => set({ center: v as Center })} options={[
              { value: "auto", label: "Automático" }, { value: "nenhum", label: "Sem centro (sequencial)" }, { value: "zero", label: "Zero" },
              { value: "br", label: "Referência do Brasil" }, { value: "mediana", label: "Mediana dos territórios" }]} />
          </Field>
          <Field label="Escala de cores">
            <Select value={shared.palette} onChange={(palette) => set({ palette })} options={PALETTES.map((p) => ({ value: p.id, label: p.name }))} />
          </Field>
        </div>
        <details className="mt-2 text-xs text-muted">
          <summary className="cursor-pointer select-none hover:text-ink">Como ler esta classificação</summary>
          <p className="mt-1.5 leading-relaxed">
            {shared.method === "continua" && "Contínua: a cor acompanha o valor, sem classes. A escala automática passa a logarítmica quando a distribuição é muito assimétrica; com 30 ou mais territórios, os 2% extremos de cada ponta recebem a cor do limite. Com ponto central, o tom do meio da paleta fica no centro e cada lado tem amplitude própria: no automático, isso ocorre quando há valores positivos e negativos; na variação entre períodos, o centro é a variação do Brasil. A paleta “Automática” usa azul-verde e troca para vermelho–azul quando há ponto central; qualquer outra paleta escolhida é sempre respeitada."}
            {shared.method === "jenks" && "Quebras naturais: os limites são postos onde há saltos nos valores, reunindo territórios parecidos e separando os discrepantes. Em mapas com muitos territórios os limites são aproximados por amostragem. Vale também para a variação entre períodos; o ponto central só existe na classificação contínua."}
            {shared.method === "quantis" && "Quantis: cada classe reúne aproximadamente o mesmo número de territórios — destaca a posição relativa, não a distância entre valores."}
            {shared.method === "iguais" && "Intervalos iguais: classes com a mesma amplitude de valores — distribuições assimétricas concentram territórios nas primeiras classes."}
            {shared.method === "geometrico" && "Progressão geométrica: limites crescem multiplicativamente — adequada a distribuições muito assimétricas; ignora valores ≤ 0."}
          </p>
        </details>
      </div>
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="relative h-[52vh] min-h-[340px] lg:h-[62vh]">
          <ChoroMap
            level={shared.level} values={values} colorOf={colorOf} uf={uf}
            format={(v) => (ok ? fmtValue(v, unit) : "—")} selected={selCodes}
            onSelect={onToggle} hovered={hov} onHover={onHover} focus={focusBox} outlines={outlines} selectionFull={sel.length >= MAX_SEL}
            ariaLabel={ok ? `Mapa: ${legendTitle}, ${LEVEL_NAMES[shared.level]}, ${legendSub}` : "Mapa"}
          />
          {!spec && (
            <div className="pointer-events-none absolute inset-x-0 top-3 flex justify-center px-14">
              <p className="rounded border border-line bg-surface/95 px-3 py-2 text-center text-sm shadow">
                Mapa em branco. Escolha um <span className="font-medium">indicador</span> acima para colorir os territórios.
              </p>
            </div>
          )}
          {spec && (loading || (variation && hist.loading)) && <span className="absolute left-3 top-3 rounded bg-surface px-2 py-1 text-xs text-muted shadow">Atualizando…</span>}
          {ok && (
            <div className="absolute bottom-3 left-3 max-w-[70%] rounded border border-line bg-surface/95 p-2.5 text-xs shadow">
              <div className="mb-1 font-medium">{legendTitle} <span className="font-normal text-muted">({legendSub})</span></div>
              {scale ? (
                <div className="w-72 max-w-full">
                  <div className="h-3 w-full border border-line" style={{ background: scale.gradient }} role="img" aria-label="Gradiente de cores, do menor para o maior valor" />
                  <div className="num mt-0.5 flex justify-between text-[10px] leading-tight">
                    {scale.ticks.map((t, i) => (
                      <span key={i} className="whitespace-nowrap">{i === 0 && scale.clampLo ? "≤ " : i === scale.ticks.length - 1 && scale.clampHi ? "≥ " : ""}{fmtValue(t, unit, { unit: false })}</span>
                    ))}
                  </div>
                  <div className="mt-1 text-[10px] text-muted">
                    Escala {scale.kind === "log" ? "logarítmica" : "linear"}
                    {centerLabel && scale.center !== null ? <> · divergente, centro em <span className="num">{fmtValue(scale.center, unit)}</span> ({centerLabel}); cada lado tem amplitude própria</> : " · cada valor tem um tom próprio"}
                  </div>
                  {scale.logDenied && <div className="mt-1 text-[10px] text-warn">Escala logarítmica não se aplica a estes valores (há negativos ou o centro não é positivo): usando a linear.</div>}
                  {scale.nonPositive > 0 && <div className="mt-1 text-[10px] text-muted">{scale.nonPositive} território(s) com valor zero{scale.kind === "log" ? " ficam na cor mínima (escala logarítmica)" : ""}.</div>}
                  {shared.center === "br" && scale.center === null && <div className="mt-1 text-[10px] text-warn">{brMap.loading || brHist.loading ? "Buscando a referência do Brasil…" : "Sem referência do Brasil para este indicador: escala não centrada."}</div>}
                </div>
              ) : (
                <ul className="space-y-0.5">
                  {legend.map((l) => (
                    <li key={l.label} className="flex items-center gap-2"><span className="inline-block h-3 w-5 border border-line" style={{ background: l.color }} /><span className="num">{l.label}</span></li>
                  ))}
                </ul>
              )}
              {!scale && shared.method === "geometrico" && nonPositive > 0 && (
                <div className="mt-1 max-w-72 text-[10px] text-warn">A progressão geométrica só considera valores positivos: {nonPositive} território(s) com valor zero ou negativo ficam na primeira classe. Para este indicador, prefira quantis ou quebras naturais.</div>
              )}
              {!scale && classCross && shared.palette === "auto" && <div className="mt-1 text-[10px] text-muted">Cores alinhadas ao zero: vermelho abaixo, azul acima.</div>}
              <div className="mt-1 flex items-center gap-2"><span className="inline-block h-3 w-5 border border-line" style={{ background: cssVar("--missing") }} />Sem dado ({nMissing})</div>
            </div>
          )}
        </div>
        {ok && (
          <div className="h-80 xl:h-[62vh]">
            <RankPanel
              spec={spec} level={shared.level} period={ok.period} real={shared.real} uf={uf} meta={unit} values={values}
              colorOf={colorOf} selected={sel} hovered={hov} onHover={onHover} onSelect={onToggle} override={rankOverride}
            />
          </div>
        )}
      </div>
      {sel.length >= 2 && (
        <section aria-label="Mapas aproximados dos territórios selecionados">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Cada território de perto</h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4">
            {sel.map((x, i) => {
              if (containers.has(x.code)) return null;
              const shape = outlines.find((f) => (f.properties as { code: string }).code === x.code);
              const v = values.get(x.code);
              return (
                <figure key={x.code} className="min-w-0">
                  <figcaption className="mb-1 flex items-baseline justify-between gap-2 text-sm">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span aria-hidden className="inline-block h-3 w-3 shrink-0 rounded-full" style={{ background: `var(--series-${(i % 8) + 1})` }} />
                      <span className="truncate font-medium">{x.code === "BR" ? "Todo o Brasil" : x.name}</span>
                    </span>
                    {ok && x.level === shared.level && <span className="num shrink-0 text-xs text-muted">{v === null || v === undefined ? "sem dado" : fmtValue(v, unit)}</span>}
                  </figcaption>
                  <div className="h-56">
                    <ChoroMap
                      compact level={shared.level} values={values} colorOf={colorOf} uf=""
                      format={(val) => (ok ? fmtValue(val, unit) : "—")} selected={selCodes}
                      focus={shape ? bboxOf([shape]) : null} outlines={shape ? [shape] : []}
                      ariaLabel={`Mapa aproximado: ${x.name}`}
                    />
                  </div>
                </figure>
              );
            })}
          </div>
          {containers.size > 0 && (
            <p className="mt-2 text-xs text-muted">
              Sem mapa próprio: {sel.filter((x) => containers.has(x.code)).map((x) => (x.code === "BR" ? "Todo o Brasil" : x.name)).join(", ")} — {containers.size === 1 ? "contém" : "contêm"} outros territórios selecionados, que já aparecem de perto acima.
            </p>
          )}
        </section>
      )}
      {ok && stats && (
        <>
          <div className="grid grid-cols-2 gap-4 rounded-md border border-line bg-surface p-4 sm:grid-cols-5">
            <Stat label={variation ? "Territórios comparáveis" : "Territórios com dado"} value={`${stats.n}`} sub={`${nMissing} ${variation ? "sem dado em um dos períodos" : `ausentes de ${ok.n_territories}`}`} />
            <Stat label={variation ? "Variação mediana" : "Mediana"} value={fmtValue(stats.median, unit)} />
            <Stat label="Média simples" value={fmtValue(stats.mean, unit)} />
            <Stat label="P10 – P90" value={`${fmtValue(stats.p10, unit, { unit: false })} – ${fmtValue(stats.p90, unit, { unit: false })}`} />
            <Stat label="Mín. – máx." value={`${fmtValue(stats.min, unit, { unit: false })} – ${fmtValue(stats.max, unit, { unit: false })}`} />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted">Exportar mapa:</span>
            <Button onClick={() => doExport("png")}>PNG</Button>
            <Button onClick={() => doExport("svg")}>SVG</Button>
            <span className="ml-3 text-muted">Dados:</span>
            {variation && <Button onClick={variationCsv}>CSV da variação</Button>}
            {["csv", "xlsx", "json"].map((f) => (
              <a key={f} href={exportUrl(f)} className="rounded border border-line bg-surface px-3 py-1.5 uppercase hover:border-muted">{f}</a>
            ))}
          </div>
          <Provenance
            meta={variation && hOk ? hOk.meta : ok.meta} period={variation ? `${periodLabel(baseOk)} e ${periodLabel(ok.period)}` : periodLabel(ok.period)}
            extra={ok.meta.breaks.filter((b) => b.period === ok.period || (variation && baseOk && b.period > baseOk && b.period <= ok.period)).map((b) => <p key={b.period}><span className="font-medium text-warn">Quebra metodológica em {b.period}:</span> {b.note}</p>)}
          />
        </>
      )}
    </section>
  );
}

const MAP_LEVELS = new Set(LEVEL_OPTIONS.map((l) => l.value));

export default function AtlasView() {
  const sp = useSearchParams();
  const params = useParams<{ code?: string }>();
  const [money] = useMoney();
  const [sharedState, setShared] = useState<Shared>({
    level: sp.get("level") ?? "MUN", uf: sp.get("uf") ?? "", real: false, method: "continua", scale: "auto", center: "auto", k: 5, palette: "auto",
  });
  // valores monetários: escolha global do site (reais, IPCA, dólares ou ouro)
  const shared = useMemo(() => ({ ...sharedState, real: money }), [sharedState, money]);
  const [sel, setSel] = useState<Sel[]>([]);
  const [hov, setHov] = useState<string | null>(null);
  const [focus, setFocus] = useState(sp.get("var") ?? "");
  const set = (p: Partial<Shared>) => setShared((s) => ({ ...s, ...p }));
  const initial = sp.get("var") ?? "";

  // Seleção inicial vinda do endereço: /territorios/{código} ou ?codes=a,b,c
  const initialCodes = params.code ?? sp.get("codes") ?? "";
  const levelInUrl = !!sp.get("level");
  useEffect(() => {
    const codes = initialCodes.split(",").map((c) => c.trim()).filter(Boolean).slice(0, MAX_SEL);
    if (!codes.length) return;
    let alive = true;
    Promise.all(codes.map((c) => api<Territory>(`/api/territories/${c}`).catch(() => null))).then((ts) => {
      if (!alive) return;
      const ok = ts.filter(Boolean) as Territory[];
      setSel(ok.map((t) => ({ code: t.code, name: t.name, level: t.level, uf: t.uf })));
      // um único território: o mapa abre no nível dele (o Brasil abre no nível das UFs)
      const lv = ok.length === 1 ? (ok[0].level === "BR" ? "UF" : ok[0].level) : null;
      if (lv && MAP_LEVELS.has(lv) && !levelInUrl) setShared((s) => ({ ...s, level: lv }));
    });
    return () => { alive = false; };
  }, [initialCodes, levelInUrl]);

  const toggle = useCallback((code: string, name: string, level?: string, uf?: string | null) => {
    setSel((cur) => (cur.some((s) => s.code === code) ? cur.filter((s) => s.code !== code)
      : cur.length >= MAX_SEL ? cur : [...cur, { code, name, level: level ?? shared.level, uf }]));
  }, [shared.level]);
  const onToggle = useCallback((code: string, name: string) => toggle(code, name), [toggle]);

  // Enquadramento: o mapa aproxima no conjunto dos territórios selecionados (o Brasil não tem polígono próprio).
  const [focusBox, setFocusBox] = useState<Box | null>(null);
  const [outlines, setOutlines] = useState<GeoJSON.Feature[]>([]);
  useEffect(() => {
    let alive = true;
    const targets = sel.filter((x) => MAP_LEVELS.has(x.level));
    Promise.all([...new Set(targets.map((x) => x.level))].map(async (lv) => [lv, await loadGeo(lv)] as const)).then((geos) => {
      if (!alive) return;
      const by = new Map(geos);
      const feats: GeoJSON.Feature[] = [];
      sel.forEach((x, i) => {
        const f = by.get(x.level)?.features.find((g) => String((g.properties as { code: string }).code) === x.code);
        if (f) feats.push({ type: "Feature", geometry: f.geometry, properties: { code: x.code, i } });
      });
      setOutlines(feats);
      setFocusBox(bboxOf(feats));
    }).catch(() => { if (alive) { setOutlines([]); setFocusBox(null); } });
    return () => { alive = false; };
  }, [sel]);

  // Hierarquia: um selecionado que contém outro (o estado de um município escolhido, "Todo o Brasil") não precisa
  // de mapa próprio — o mapa do território menor já fica dentro dele.
  const [parents, setParents] = useState<Record<string, string[]>>({});
  useEffect(() => {
    const missing = sel.filter((x) => x.code !== "BR" && !(x.code in parents));
    if (!missing.length) return;
    let alive = true;
    Promise.all(missing.map((x) => api<Territory & { regiao_code?: string | null; rgint_code?: string | null; rgi_code?: string | null }>(`/api/territories/${x.code}`)
      .then((t) => [x.code, [t.rgi_code, t.rgint_code, t.uf_code, t.regiao_code].filter((c): c is string => !!c && c !== x.code)] as const)
      .catch(() => [x.code, [] as string[]] as const))).then((got) => { if (alive) setParents((cur) => ({ ...cur, ...Object.fromEntries(got) })); });
    return () => { alive = false; };
  }, [sel, parents]);
  const containers = useMemo(() => {
    const out = new Set<string>();
    for (const x of sel) for (const p of parents[x.code] ?? []) if (sel.some((y) => y.code === p)) out.add(p);
    if (sel.length > 1 && sel.some((x) => x.code === "BR")) out.add("BR");
    return out;
  }, [sel, parents]);

  // Sugestões de comparação a partir do último território escolhido.
  const ufs = useUfs();
  const last = sel[sel.length - 1];
  const full = sel.length >= MAX_SEL;
  const has = (code: string) => sel.some((x) => x.code === code);
  const lastUf = last && UF_LEVELS.has(last.level) ? ufs.find((u) => u.code === last.code.slice(0, 2)) : undefined;
  // o clique no mapa não informa a UF: ela sai dos dois primeiros dígitos do código do município
  const siglaOf = (x: Sel) => x.uf ?? ufs.find((u) => u.code === x.code.slice(0, 2))?.sigla ?? null;
  const [simBusy, setSimBusy] = useState(false);
  const addSimilar = async () => {
    if (!last) return;
    setSimBusy(true);
    try {
      const r = await api<{ items: { code: string; name: string; uf: string | null }[] }>(`/api/similar/${last.code}?n=6`);
      setSel((cur) => {
        const add = r.items.filter((i) => !cur.some((x) => x.code === i.code)).slice(0, Math.min(3, MAX_SEL - cur.length));
        return [...cur, ...add.map((i) => ({ code: i.code, name: i.name, level: last.level, uf: i.uf }))];
      });
    } catch { /* sem semelhantes: nada a adicionar */ } finally { setSimBusy(false); }
  };
  const sugCls = "rounded-full border border-dashed border-line px-2.5 py-0.5 hover:border-accent hover:text-accent disabled:opacity-50";

  return (
    <div className="mx-auto max-w-[1600px] px-4 py-4">
      <div className="min-w-0">
        <h1 className="font-serif text-2xl font-semibold tracking-tight">Explorar</h1>
        <p className="max-w-3xl text-sm text-muted">Monte o seu mapa: escolha um indicador para colorir os territórios e selecione os lugares que quer ver de perto. Um território abre o perfil; dois ou mais, a comparação.</p>
      </div>

      <section aria-label="Territórios selecionados" className="mt-3 rounded-md border border-line bg-surface p-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <h2 className="text-sm font-medium">{sel.length === 0 ? "Escolha os territórios" : sel.length === 1 ? "1 território selecionado" : `Comparando ${sel.length} territórios`}
            <span className="ml-2 font-normal text-muted">até {MAX_SEL}</span></h2>
          <div className="w-full sm:w-96">
            {full ? <p className="rounded border border-line px-2.5 py-1.5 text-sm text-muted">Seleção cheia: remova um território para adicionar outro.</p>
              : <TerritorySearch onPick={(t) => toggle(t.code, t.name, t.level, t.uf)} exclude={sel.map((x) => x.code)}
                  placeholder={sel.length ? "Adicionar município, estado ou região…" : "Buscar município, estado ou região…"} />}
          </div>
          {sel.length > 0 && (
            <div className="ml-auto flex items-center gap-2 text-sm">
              <button type="button" className="text-muted underline hover:text-ink" onClick={() => setSel([])}>Limpar</button>
              <a href="#selecao" className="rounded bg-accent px-3 py-1.5 font-medium text-accent-ink">{sel.length === 1 ? "Ver perfil ↓" : `Ver comparação (${sel.length}) ↓`}</a>
            </div>
          )}
        </div>
        {sel.length === 0 ? (
          <p className="mt-2 text-sm text-muted">Busque pelo nome acima ou clique direto no mapa ou no ranking. O mapa aproxima no que você escolher e, a partir de dois territórios, cada um ganha também um mapa próprio, de perto. Clique de novo num território para tirá-lo da seleção.</p>
        ) : (
          <>
            <ul className="mt-2.5 flex flex-wrap gap-1.5 text-sm">
              {sel.map((x, i) => (
                <li key={x.code} className="flex items-center gap-1.5 rounded border border-line bg-surface-2 py-1 pl-2 pr-1">
                  <span aria-hidden className="inline-block h-3 w-3 rounded-full" style={{ background: `var(--series-${(i % 8) + 1})` }} />
                  {x.code === "BR" ? "Todo o Brasil" : x.name}{x.level === "MUN" && siglaOf(x) ? ` (${siglaOf(x)})` : ""}
                  <button type="button" onClick={() => setSel(sel.filter((y) => y.code !== x.code))} aria-label={`Remover ${x.name} da seleção`}
                    className="grid h-5 w-5 place-items-center rounded text-muted hover:bg-surface hover:text-danger">×</button>
                </li>
              ))}
            </ul>
            {!full && last && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-muted">
                {(last.level !== "BR" || (lastUf && !has(lastUf.code)) || !has("BR")) && <span>Comparar com:</span>}
                {last.level !== "BR" && <button type="button" className={sugCls} disabled={simBusy} onClick={addSimilar}>+ parecidos com {last.name}</button>}
                {lastUf && !has(lastUf.code) && <button type="button" className={sugCls} onClick={() => toggle(lastUf.code, lastUf.name, "UF", lastUf.uf)}>+ {lastUf.name} (estado)</button>}
                {!has("BR") && <button type="button" className={sugCls} onClick={() => toggle("BR", "Brasil", "BR", null)}>+ Todo o Brasil</button>}
                <span>A cor de cada etiqueta é a do contorno no mapa e das linhas nos gráficos.{sel.length >= 2 ? " Abaixo do mapa há um mapa aproximado de cada território (menos dos que contêm outros selecionados)." : ""}</span>
              </div>
            )}
          </>
        )}
      </section>

      <div className="mt-3 grid max-w-2xl grid-cols-2 gap-3 rounded-md border border-line bg-surface p-3">
        <Field label="Nível territorial">
          <Select value={shared.level} onChange={(level) => set({ level })} options={LEVEL_OPTIONS} />
        </Field>
        <Field label="Recorte" hint={UF_LEVELS.has(shared.level) ? undefined : "Não se aplica a este nível."}>
          {UF_LEVELS.has(shared.level) ? <UfSelect value={shared.uf} onChange={(uf) => set({ uf })} />
            : <select className="w-full rounded border border-line bg-surface px-2.5 py-1.5 text-sm opacity-50" disabled aria-label="Recorte"><option>Todo o Brasil</option></select>}
        </Field>
      </div>

      <div className="mt-4">
        <MapPanel shared={shared} set={set} initial={initial} initialPeriod={sp.get("period")}
          sel={sel} hov={hov} onHover={setHov} onToggle={onToggle} onSpec={setFocus} focusBox={focusBox} outlines={outlines} containers={containers} />
      </div>

      <div id="selecao" className="mt-8 scroll-mt-20">
        {sel.length === 1 && <ProfileBody key={sel[0].code} code={sel[0].code} />}
        {sel.length >= 2 && <TerritorialCompare terrs={sel} focus={!focus || focus.startsWith("=") ? undefined : focus} />}
        {sel.length === 0 && (
          <p className="rounded-md border border-dashed border-line p-6 text-center text-sm text-muted">
            Selecione um território para ver o perfil completo aqui, ou dois ou mais para compará-los.
          </p>
        )}
      </div>
      <p className="sr-only" aria-live="polite">{sel.length === 1 ? `Perfil de ${sel[0].name} exibido abaixo do mapa.` : sel.length > 1 ? `Comparação de ${fmtNum(sel.length, 0)} territórios exibida abaixo do mapa.` : ""}</p>
    </div>
  );
}
