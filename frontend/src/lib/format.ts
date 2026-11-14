const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

export const LEVEL_NAMES: Record<string, string> = {
  BR: "Brasil", REGIAO: "Grandes regiões", UF: "Unidades da Federação", RGINT: "Regiões intermediárias",
  RGI: "Regiões imediatas", MUN: "Municípios",
};
export const LEVEL_SINGULAR: Record<string, string> = {
  BR: "País", REGIAO: "Grande região", UF: "Unidade da Federação", RGINT: "Região geográfica intermediária",
  RGI: "Região geográfica imediata", MUN: "Município",
};
export const NATURE: Record<string, string> = {
  observado: "Observado", derivado: "Derivado", estimado: "Estimado", personalizado: "Personalizado",
};

export function periodLabel(p: string | null | undefined): string {
  if (!p) return "—";
  if (p.includes("-")) {
    const [y, m] = p.split("-");
    return `${MONTHS[Number(m) - 1]}/${y}`;
  }
  return p;
}

export function fmtNum(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return v.toLocaleString("pt-BR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** Forma compacta para grandes magnitudes: 1,07 tri · 12,4 bi · 3,2 mi. */
export function fmtCompact(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e12) return fmtNum(v / 1e12, 2) + " tri";
  if (a >= 1e9) return fmtNum(v / 1e9, 2) + " bi";
  if (a >= 1e6) return fmtNum(v / 1e6, 2) + " mi";
  if (a >= 1e4) return fmtNum(v, 0);
  return fmtNum(v, decimals);
}

type UnitLike = { unit: string; decimals?: number; percent?: boolean };

export function fmtValue(v: number | null | undefined, m: UnitLike, opts: { unit?: boolean } = {}): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const d = m.decimals ?? 2;
  const showUnit = opts.unit !== false;
  // moedas: símbolo antes do número ("R$ 1,2 bi", "US$ 9.610 por habitante")
  const cur = ["R$", "US$"].find((c) => m.unit === c || m.unit.startsWith(c + " "));
  if (cur) return (showUnit ? cur + " " : "") + fmtCompact(v, d) + (showUnit ? m.unit.slice(cur.length) : "");
  if (m.unit === "%" ) return fmtNum(v, d) + (showUnit ? "%" : "");
  const s = Math.abs(v) >= 1e6 ? fmtCompact(v, d) : fmtNum(v, d);
  return showUnit && !["razão", "índice"].includes(m.unit) ? `${s} ${m.unit}` : s;
}

export function axisFmt(v: number): string {
  const a = Math.abs(v);
  if (a >= 1e12) return fmtNum(v / 1e12, 1) + " tri";
  if (a >= 1e9) return fmtNum(v / 1e9, 1) + " bi";
  if (a >= 1e6) return fmtNum(v / 1e6, 1) + " mi";
  if (a >= 1e3) return fmtNum(v / 1e3, a >= 1e4 ? 0 : 1) + " mil";
  return fmtNum(v, a < 10 && a !== 0 ? 1 : 0);
}

export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined) return "—";
  if (p < 0.001) return "< 0,001";
  return fmtNum(p, 3);
}

export function download(filename: string, content: Blob | string, type = "text/plain") {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

export function slug(s: string): string {
  return s.normalize("NFKD").replace(/[^\w\s-]/g, "").trim().toLowerCase().replace(/\s+/g, "-").slice(0, 60);
}
