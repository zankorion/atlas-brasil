"use client";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api, getCustom, qs, useApi, type AppMeta, type CustomIndicator, type Indicator, type Territory } from "@/lib/api";
import { periodLabel } from "@/lib/format";
import { inputCls } from "./ui";

export function useCatalog() {
  const inds = useApi<Indicator[]>("/api/indicators");
  const meta = useApi<AppMeta>("/api/meta");
  const [custom, setCustom] = useState<CustomIndicator[]>([]);
  useEffect(() => {
    const load = () => setCustom(getCustom());
    const id = requestAnimationFrame(load);
    window.addEventListener("atlas:custom", load);
    return () => {
      cancelAnimationFrame(id);
      window.removeEventListener("atlas:custom", load);
    };
  }, []);
  return { indicators: inds.data ?? [], dimensions: meta.data?.dimensions ?? [], meta: meta.data, custom, error: inds.error ?? meta.error, loading: inds.loading };
}

/** Seletor de indicador agrupado por dimensão; inclui indicadores personalizados salvos. */
export function IndicatorSelect({ value, onChange, level, frequency, label = "Indicador", allowCustom = true }: {
  value: string; onChange: (v: string) => void; level?: string; frequency?: "A" | "M"; label?: string; allowCustom?: boolean;
}) {
  const { indicators, dimensions, custom } = useCatalog();
  const groups = useMemo(() => {
    const ok = indicators.filter((i) => i.status === "disponivel" && (!level || i.levels.includes(level)) && (!frequency || i.frequency === frequency));
    return dimensions.map((d) => ({ d, items: ok.filter((i) => i.dimension === d.id) })).filter((g) => g.items.length);
  }, [indicators, dimensions, level, frequency]);
  const known = value.startsWith("=") ? custom.some((c) => "=" + c.expr === value) : true;
  return (
    <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)} aria-label={label}>
      {groups.length === 0 && <option value={value}>Carregando…</option>}
      {groups.map((g) => (
        <optgroup key={g.d.id} label={g.d.name}>
          {g.items.map((i) => (
            <option key={i.id} value={i.id}>{i.short_name !== i.name ? `${i.short_name} — ${i.name}` : i.name}</option>
          ))}
        </optgroup>
      ))}
      {allowCustom && frequency !== "M" && (custom.length > 0 || !known) && (
        <optgroup label="Personalizados (salvos neste navegador)">
          {custom.map((c) => <option key={c.expr} value={"=" + c.expr}>{c.name}</option>)}
          {!known && <option value={value}>{value}</option>}
        </optgroup>
      )}
    </select>
  );
}

export function PeriodSelect({ value, onChange, periods, label = "Período" }: {
  value: string | null; onChange: (v: string) => void; periods: string[]; label?: string;
}) {
  return (
    <select className={inputCls} value={value ?? ""} onChange={(e) => onChange(e.target.value)} aria-label={label} disabled={!periods.length}>
      {!periods.length && <option value="">Sem dados</option>}
      {[...periods].reverse().map((p) => <option key={p} value={p}>{periodLabel(p)}</option>)}
    </select>
  );
}

export function usePeriods(spec: string | null, level: string) {
  const r = useApi<{ periods: string[] }>(spec ? `/api/periods${qs({ var: spec, level })}` : null);
  return { periods: r.data?.periods ?? [], error: r.error, loading: r.loading };
}

export const LEVEL_OPTIONS = [
  { value: "MUN", label: "Municípios" },
  { value: "RGI", label: "Regiões imediatas" },
  { value: "RGINT", label: "Regiões intermediárias" },
  { value: "UF", label: "Unidades da Federação" },
  { value: "REGIAO", label: "Grandes regiões" },
];

export function useUfs() {
  const r = useApi<Territory[]>("/api/territories?level=UF&limit=40");
  return r.data ?? [];
}

export function UfSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ufs = useUfs();
  return (
    <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)} aria-label="Unidade da Federação">
      <option value="">Todo o Brasil</option>
      {ufs.map((u) => <option key={u.code} value={u.code}>{u.name}</option>)}
    </select>
  );
}

const LV: Record<string, string> = { BR: "País", REGIAO: "Região", UF: "UF", RGINT: "Reg. intermediária", RGI: "Reg. imediata", MUN: "Município" };

/** Busca de territórios por nome (com acento ou sem) ou código IBGE. */
export function TerritorySearch({ onPick, level, placeholder = "Buscar município, estado ou região…", exclude = [] }: {
  onPick: (t: Territory) => void; level?: string; placeholder?: string; exclude?: string[];
}) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<Territory[]>([]);
  const [open, setOpen] = useState(false);
  const [idx, setIdx] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const listId = useId();
  useEffect(() => {
    if (q.trim().length < 2) return;
    const t = setTimeout(() => {
      api<Territory[]>(`/api/territories${qs({ q, level, limit: 12 })}`).then((r) => {
        setRes(r);
        setIdx(0);
        setOpen(true);
      }).catch(() => setRes([]));
    }, 180);
    return () => clearTimeout(t);
  }, [q, level]);
  useEffect(() => {
    const h = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const items = res.filter((t) => !exclude.includes(t.code));
  const pick = (t: Territory) => {
    onPick(t);
    setQ("");
    setRes([]);
    setOpen(false);
  };
  return (
    <div ref={box} className="relative">
      <input
        className={inputCls}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-label={placeholder}
        placeholder={placeholder}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => items.length && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(items.length - 1, i + 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(0, i - 1)); }
          else if (e.key === "Enter" && open && items[idx]) { e.preventDefault(); pick(items[idx]); }
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && q.trim().length >= 2 && (
        <ul id={listId} role="listbox" className="absolute z-30 mt-1 max-h-72 w-full overflow-auto rounded border border-line bg-surface shadow-lg">
          {items.length === 0 && <li className="px-3 py-2 text-sm text-muted">Nenhum território encontrado.</li>}
          {items.map((t, i) => (
            <li key={t.code} role="option" aria-selected={i === idx}>
              <button
                type="button"
                onClick={() => pick(t)}
                onMouseEnter={() => setIdx(i)}
                className={`flex w-full items-baseline justify-between gap-3 px-3 py-1.5 text-left text-sm ${i === idx ? "bg-accent-soft" : ""}`}
              >
                <span>{t.name}{t.uf && t.level !== "UF" ? <span className="text-muted"> · {t.uf}</span> : null}</span>
                <span className="shrink-0 text-xs text-muted">{LV[t.level]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function TerritoryChips({ items, onRemove }: { items: Territory[]; onRemove: (code: string) => void }) {
  if (!items.length) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-1.5">
      {items.map((t, i) => (
        <li key={t.code} className="flex items-center gap-1.5 rounded border border-line bg-surface px-2 py-1 text-sm">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: `var(--series-${(i % 8) + 1})` }} />
          {t.name}{t.uf && t.level === "MUN" ? ` (${t.uf})` : ""}
          <button type="button" onClick={() => onRemove(t.code)} aria-label={`Remover ${t.name}`} className="text-muted hover:text-danger">×</button>
        </li>
      ))}
    </ul>
  );
}
