// Rampas de cor para mapas coropléticos (âncoras do ColorBrewer, seguras para daltonismo).
const ANCHORS: Record<string, string[]> = {
  petroleo: ["#f0f6d8", "#c7e9b4", "#7fcdbb", "#41b6c4", "#1d91c0", "#225ea8", "#0c2c84"],
  ambar: ["#fff7d1", "#fee391", "#fec44f", "#fe9929", "#ec7014", "#cc4c02", "#8c2d04"],
  violeta: ["#f1eef6", "#d4c9e6", "#b3a2d3", "#8f7cc0", "#6f55ab", "#54348f", "#3b1a6d"],
  divergente: ["#b2182b", "#e0755f", "#f6c4a9", "#f2efe8", "#a9cfe3", "#5a9dc8", "#2166ac"],
};
export const PALETTES = [
  { id: "petroleo", name: "Azul-verde (sequencial)" },
  { id: "ambar", name: "Âmbar (sequencial)" },
  { id: "violeta", name: "Violeta (sequencial)" },
  { id: "divergente", name: "Vermelho–azul (divergente)" },
];

function hex(c: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16)) as [number, number, number];
}

/** Cor na posição t (0 a 1) da rampa, por interpolação linear entre as âncoras. */
export function rampAt(name: string, t: number): string {
  const a = ANCHORS[name] ?? ANCHORS.petroleo;
  const u = Math.min(1, Math.max(0, Number.isFinite(t) ? t : 0)) * (a.length - 1);
  const lo = Math.floor(u), hi = Math.min(a.length - 1, lo + 1), f = u - lo;
  const [r1, g1, b1] = hex(a[lo]), [r2, g2, b2] = hex(a[hi]);
  const mix = (x: number, y: number) => Math.round(x + (y - x) * f).toString(16).padStart(2, "0");
  return `#${mix(r1, r2)}${mix(g1, g2)}${mix(b1, b2)}`;
}

/** k cores interpoladas ao longo da rampa. */
export function ramp(name: string, k: number): string[] {
  if (k <= 1) return [rampAt(name, 1)];
  return Array.from({ length: k }, (_, i) => rampAt(name, i / (k - 1)));
}

export type ScaleMode = "auto" | "linear" | "log";
export type ContinuousScale = {
  colorOf: (v: number) => string; kind: "linear" | "log"; lo: number; hi: number;
  clampLo: boolean; clampHi: boolean; ticks: number[]; gradient: string; nonPositive: number;
  /** Ponto central da escala divergente (null = escala sequencial). */
  center: number | null;
};

function quantile(sorted: number[], q: number): number {
  const pos = (sorted.length - 1) * q, lo = Math.floor(pos), hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/**
 * Escala contínua (sem classes): cada valor recebe um tom próprio.
 * - "auto" usa escala logarítmica quando todos os valores são positivos e a distribuição é muito
 *   assimétrica (máximo >= 8 x mediana dos valores positivos); caso contrário, linear. Zeros ficam na cor mínima.
 * - Com 30 ou mais territórios, o domínio vai do percentil 2 ao 98 para que poucos valores extremos
 *   não achatem as cores dos demais; valores além desses limites recebem a cor do extremo.
 * - Com `center`, a escala é divergente: o tom neutro fica exatamente no centro e cada lado vai do centro ao
 *   extremo daquele lado. A paleta divergente é usada qualquer que seja a paleta sequencial escolhida.
 */
export function continuousScale(values: number[], palette: string, mode: ScaleMode, center: number | null = null): ContinuousScale | null {
  const all = values.filter((v) => Number.isFinite(v)).sort((x, y) => x - y);
  if (!all.length) return null;
  // Zeros não impedem a escala logarítmica: ficam na cor mínima e são contados em `nonPositive`.
  const positives = all.filter((v) => v > 0);
  const posMedian = positives.length ? quantile(positives, 0.5) : 0;
  const canLog = all[0] >= 0 && positives.length >= 2 && (center === null || center > 0);
  const kind = mode === "auto" ? (canLog && posMedian > 0 && all[all.length - 1] / posMedian >= 8 ? "log" : "linear")
    : mode === "log" && center !== null && center <= 0 ? "linear" : mode;
  const usable = kind === "log" ? all.filter((v) => v > 0) : all;
  if (!usable.length) return null;
  const robust = usable.length >= 30;
  let lo = robust ? quantile(usable, 0.02) : usable[0];
  let hi = robust ? quantile(usable, 0.98) : usable[usable.length - 1];
  if (hi <= lo) { lo = usable[0]; hi = usable[usable.length - 1]; }
  const f = kind === "log" ? Math.log : (v: number) => v;
  const inv = kind === "log" ? Math.exp : (v: number) => v;
  const nonPositive = all.length - usable.length;
  const stops = (name: string) => `linear-gradient(to right, ${Array.from({ length: 13 }, (_, i) => rampAt(name, i / 12)).join(", ")})`;
  if (center !== null) {
    // Escala divergente de dois ramos: o centro fica sempre no tom neutro e cada lado usa a sua própria
    // amplitude (do centro ao percentil extremo daquele lado). Assim uma distribuição assimétrica não
    // desperdiça metade da paleta; em troca, a mesma distância do centro pode ter intensidades diferentes
    // acima e abaixo — as marcas da legenda mostram a amplitude de cada lado.
    const c = f(center);
    const dLo = Math.max(c - f(lo), 0), dHi = Math.max(f(hi) - c, 0);
    const pos = (v: number) => {
      if (kind === "log" && v <= 0) return 0;
      const d = f(v) - c;
      if (d < 0) return dLo > 0 ? 0.5 - 0.5 * Math.min(1, -d / dLo) : 0.5;
      return dHi > 0 ? 0.5 + 0.5 * Math.min(1, d / dHi) : 0.5;
    };
    return {
      colorOf: (v) => rampAt("divergente", pos(v)), kind, lo: inv(c - dLo), hi: inv(c + dHi), center,
      clampLo: usable[0] < inv(c - dLo) || nonPositive > 0, clampHi: usable[usable.length - 1] > inv(c + dHi),
      ticks: [inv(c - dLo), inv(c - dLo / 2), center, inv(c + dHi / 2), inv(c + dHi)], gradient: stops("divergente"), nonPositive,
    };
  }
  const a = f(lo), span = f(hi) - a;
  const pos = (v: number) => (span <= 0 ? 0.5 : kind === "log" && v <= 0 ? 0 : (f(v) - a) / span);
  return {
    colorOf: (v) => rampAt(palette, pos(v)), kind, lo, hi, center: null,
    clampLo: usable[0] < lo || nonPositive > 0, clampHi: usable[usable.length - 1] > hi,
    ticks: Array.from({ length: 5 }, (_, i) => inv(a + (span * i) / 4)), gradient: stops(palette), nonPositive,
  };
}

/** Índice da classe de v dados os limites internos (k-1 limites -> k classes). */
export function classOf(v: number, breaks: number[]): number {
  let i = 0;
  while (i < breaks.length && v > breaks[i]) i++;
  return i;
}

export function cssVar(name: string): string {
  if (typeof window === "undefined") return "#888";
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}
