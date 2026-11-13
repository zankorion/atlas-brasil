"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import type { SourceRef, VarMeta } from "@/lib/api";
import { NATURE } from "@/lib/format";

export function Page({ title, lead, children, wide }: { title: string; lead?: ReactNode; children: ReactNode; wide?: boolean }) {
  return (
    <div className={`mx-auto px-4 py-6 ${wide ? "max-w-[1600px]" : "max-w-7xl"}`}>
      <h1 className="font-serif text-3xl font-semibold tracking-tight">{title}</h1>
      {lead && <p className="mt-2 max-w-3xl text-muted">{lead}</p>}
      <div className="mt-6">{children}</div>
    </div>
  );
}

export function Card({ title, children, className = "", actions }: { title?: ReactNode; children: ReactNode; className?: string; actions?: ReactNode }) {
  return (
    <section className={`min-w-0 rounded-md border border-line bg-surface ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "w-full rounded border border-line bg-surface px-2.5 py-1.5 text-sm text-ink disabled:opacity-50";

export function Select({ value, onChange, options, disabled, ariaLabel }: {
  value: string; onChange: (v: string) => void; options: { value: string; label: string }[]; disabled?: boolean; ariaLabel?: string;
}) {
  return (
    <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} aria-label={ariaLabel}>
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

export function Seg<T extends string>({ value, onChange, options, label }: {
  value: T; onChange: (v: T) => void; options: { value: T; label: string }[]; label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex flex-wrap overflow-hidden rounded border border-line">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`px-3 py-1.5 text-sm ${value === o.value ? "bg-accent text-accent-ink" : "bg-surface text-muted hover:text-ink"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Check({ checked, onChange, label, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; disabled?: boolean }) {
  return (
    <label className={`flex items-center gap-2 text-sm ${disabled ? "opacity-50" : ""}`}>
      <input type="checkbox" className="h-4 w-4 accent-[var(--accent)]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

export function Button({ children, onClick, variant = "ghost", disabled, type = "button", title }: {
  children: ReactNode; onClick?: () => void; variant?: "primary" | "ghost"; disabled?: boolean; type?: "button" | "submit"; title?: string;
}) {
  const cls = variant === "primary" ? "bg-accent text-accent-ink border-accent" : "bg-surface text-ink border-line hover:border-muted";
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} className={`rounded border px-3 py-1.5 text-sm disabled:opacity-50 ${cls}`}>
      {children}
    </button>
  );
}

export function Notice({ kind = "info", children }: { kind?: "info" | "warn" | "error"; children: ReactNode }) {
  const cls = kind === "warn" ? "border-warn/40 bg-warn-bg text-warn" : kind === "error" ? "border-danger/40 text-danger" : "border-line bg-surface-2 text-muted";
  return (
    <div role={kind === "error" ? "alert" : "note"} className={`rounded border px-3 py-2 text-sm ${cls}`}>
      {children}
    </div>
  );
}

export function Loading({ label = "Carregando dados…" }: { label?: string }) {
  return <p role="status" className="py-6 text-center text-sm text-muted">{label}</p>;
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="num mt-0.5 text-lg font-medium">{value}</div>
      {sub && <div className="text-xs text-muted">{sub}</div>}
    </div>
  );
}

export function Tabs<T extends string>({ value, onChange, tabs }: { value: T; onChange: (v: T) => void; tabs: { id: T; label: string }[] }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-x-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm ${value === t.id ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-ink"}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function NatureTag({ nature }: { nature: string }) {
  const cls = nature === "observado" ? "border-line text-muted" : "border-warn/50 text-warn";
  return <span className={`inline-block rounded-sm border px-1.5 py-px text-[11px] uppercase tracking-wide ${cls}`}>{NATURE[nature] ?? nature}</span>;
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  const [d] = iso.split("T");
  const [y, m, dd] = d.split("-");
  return `${dd}/${m}/${y}`;
}

/** Rodapé de rastreabilidade: fonte, publicação, natureza, notas e limitações de uma variável. */
export function Provenance({ meta, period, extra }: { meta: VarMeta; period?: string; extra?: ReactNode }) {
  return (
    <div className="space-y-1.5 border-t border-line pt-3 text-xs leading-relaxed text-muted">
      <p>
        <NatureTag nature={meta.nature} />{" "}
        <strong className="font-medium text-ink">{meta.name}</strong> · unidade: {meta.unit}
        {meta.real ? " (preços constantes)" : meta.unit.startsWith("R$") ? " (preços correntes)" : ""}
        {period ? ` · referência: ${period}` : ""}
        {meta.formula && <> · fórmula: <code className="num">{meta.formula}</code></>}
      </p>
      {meta.sources.length > 0 && (
        <p>
          Fonte{meta.sources.length > 1 ? "s" : ""}:{" "}
          {meta.sources.map((s: SourceRef, i) => (
            <span key={s.dataset_id}>
              {i > 0 && "; "}
              {s.source} — {s.dataset}
              {s.updated_at && ` (carga de ${fmtDate(s.updated_at)})`}
            </span>
          ))}
          .
        </p>
      )}
      {meta.notes.map((n) => <p key={n}>{n}</p>)}
      {meta.div_zero > 0 && <p>{meta.div_zero} observação(ões) com divisor zero foram tratadas como ausentes.</p>}
      {meta.limitations && <p><span className="font-medium text-warn">Limitações:</span> {meta.limitations}</p>}
      {extra}
      {meta.methodology_id && (
        <p>
          <Link className="text-accent underline" href={`/fontes#m-${meta.methodology_id}`}>Ver metodologia</Link>
        </p>
      )}
    </div>
  );
}

/** Texto de metodologia em Markdown simples (parágrafos, listas e negrito). */
export function Markdown({ text }: { text: string }) {
  const inline = (s: string, key: number) => {
    const parts = s.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g);
    return (
      <span key={key}>
        {parts.map((p, i) =>
          p.startsWith("**") ? <strong key={i}>{p.slice(2, -2)}</strong>
          : p.startsWith("`") ? <code key={i}>{p.slice(1, -1)}</code>
          : p.startsWith("*") && p.length > 2 ? <em key={i}>{p.slice(1, -1)}</em> : p)}
      </span>
    );
  };
  const blocks: ReactNode[] = [];
  let list: string[] = [], ordered = false, para: string[] = [];
  const flush = () => {
    if (para.length) blocks.push(<p key={blocks.length}>{inline(para.join(" "), 0)}</p>);
    if (list.length) {
      const items = list.map((l, i) => <li key={i}>{inline(l, i)}</li>);
      blocks.push(ordered ? <ol key={blocks.length}>{items}</ol> : <ul key={blocks.length}>{items}</ul>);
    }
    para = []; list = [];
  };
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const m = line.match(/^\s*(-|\d+\.)\s+(.*)$/);
    if (!line.trim()) flush();
    else if (m) {
      if (para.length) flush();
      ordered = m[1] !== "-";
      list.push(m[2]);
    } else if (list.length && /^\s{2,}/.test(raw)) list[list.length - 1] += " " + line.trim();
    else {
      if (list.length) flush();
      para.push(line.trim());
    }
  }
  flush();
  return <div className="prose-atlas text-sm">{blocks}</div>;
}
