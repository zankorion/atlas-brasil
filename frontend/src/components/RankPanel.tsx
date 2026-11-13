"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { qs, useApi, type VarMeta } from "@/lib/api";
import { fmtNum, fmtValue } from "@/lib/format";

type Row = { rank: number; code: string; name: string; uf: string | null; value: number };
type Resp = { meta: VarMeta; level: string; period: string; n_ranked: number; n_missing: number; rows: Row[] };
const LIMIT = 30;
export type RankItem = { code: string; name: string; uf: string | null; value: number };

type Props = {
  spec: string; level: string; period: string; real: boolean; uf: string;
  /** Unidade e casas decimais para exibir os valores. */
  meta: { unit: string; decimals?: number };
  values: Map<string, number | null>;
  colorOf: (v: number) => string;
  selected: { code: string; name: string }[];
  hovered: string | null;
  onHover: (code: string | null) => void;
  onSelect: (code: string, name: string) => void;
  /** Lista já calculada (ex.: variação entre dois períodos); quando presente, o ranking não consulta a API. */
  override?: { rows: RankItem[]; missing: number; title: string } | null;
};

/**
 * Ranking em barras ligado ao mapa. A cor de cada barra é a mesma do território no mapa; o comprimento é
 * proporcional ao valor (escala linear a partir de zero), o que permite comparar magnitudes que a cor não mostra.
 */
export function RankPanel({ spec, level, period, real, uf, meta, values, colorOf, selected, hovered, onHover, onSelect, override }: Props) {
  const [order, setOrder] = useState<"desc" | "asc">("desc");
  const { data, error } = useApi<Resp>(override ? null : `/api/lab/ranking${qs({ var: spec, level, period, real, uf, n: LIMIT, order })}`);
  const ok = !override && data && data.meta.spec === spec && data.level === level && data.period === period ? data : null;
  const total = override ? override.rows.length : ok?.n_ranked ?? 0;
  const missing = override ? override.missing : ok?.n_missing ?? 0;
  const rows = useMemo<Row[]>(() => {
    if (!override) return ok?.rows ?? [];
    const sorted = [...override.rows].sort((a, b) => (order === "desc" ? b.value - a.value : a.value - b.value));
    return sorted.slice(0, LIMIT).map((r, i) => ({ ...r, rank: i + 1 }));
  }, [override, ok, order]);
  const ready = !!override || !!ok;
  const max = useMemo(() => Math.max(0, ...rows.map((r) => Math.abs(r.value))), [rows]);
  const pos = (r: Row) => (order === "desc" ? r.rank : total - r.rank + 1);
  const selRef = useRef<HTMLLIElement>(null);
  const selCodes = useMemo(() => new Set(selected.map((s) => s.code)), [selected]);
  const last = selected[selected.length - 1];
  useEffect(() => {
    selRef.current?.scrollIntoView({ block: "nearest" });
  }, [last?.code]);

  // Selecionados fora da lista visível: ficam fixos no rodapé, com a posição calculada.
  const pinned = useMemo(() => {
    const listed = new Set(rows.map((r) => r.code));
    const out: Row[] = [];
    for (const s of selected) {
      const v = values.get(s.code);
      if (listed.has(s.code) || v === null || v === undefined) continue;
      let above = 0;
      values.forEach((x) => { if (x !== null && x > v) above++; });
      out.push({ rank: above + 1, code: s.code, name: s.name, uf: null, value: v });
    }
    return out.sort((a, b) => a.rank - b.rank);
  }, [selected, rows, values]);
  const hasNegative = rows.some((r) => r.value < 0);

  const item = (r: Row, position: number, pin = false) => {
    const isSel = selCodes.has(r.code), isHov = hovered === r.code;
    return (
      <li key={(pin ? "pin-" : "") + r.code} ref={r.code === last?.code && !pin ? selRef : undefined}>
        <button
          type="button"
          onClick={() => onSelect(r.code, r.name)}
          onMouseEnter={() => onHover(r.code)} onMouseLeave={() => onHover(null)}
          onFocus={() => onHover(r.code)} onBlur={() => onHover(null)}
          aria-pressed={isSel}
          className={`grid w-full grid-cols-[2.25rem_1fr_auto] items-center gap-x-2 px-3 py-1 text-left text-sm ${isSel ? "bg-accent-soft" : isHov ? "bg-surface-2" : ""}`}
        >
          <span className="num text-xs text-muted">{position}º</span>
          <span className="min-w-0">
            <span className={`block truncate ${isSel ? "font-medium" : ""}`}>{r.name}{r.uf ? <span className="text-muted"> · {r.uf}</span> : null}</span>
            <span className="mt-0.5 block h-2 rounded-sm border border-muted/50" style={{ width: `${max > 0 ? Math.max(1.5, (Math.abs(r.value) / max) * 100) : 1.5}%`, background: colorOf(r.value) }} />
          </span>
          <span className="num text-xs">{fmtValue(r.value, meta, { unit: meta.unit === "%" })}</span>
        </button>
      </li>
    );
  };

  return (
    <aside aria-label="Ranking dos territórios" className="flex h-full min-h-0 flex-col rounded-md border border-line bg-surface">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h3 className="text-sm font-semibold">{override?.title ?? "Ranking"} <span className="font-normal text-muted">· {meta.unit}</span></h3>
        {total > LIMIT && (
          <div role="group" aria-label="Ordem do ranking" className="inline-flex overflow-hidden rounded border border-line text-xs">
            {(["desc", "asc"] as const).map((o) => (
              <button key={o} type="button" aria-pressed={order === o} onClick={() => setOrder(o)}
                className={`px-2 py-1 ${order === o ? "bg-accent text-accent-ink" : "text-muted hover:text-ink"}`}>{o === "desc" ? "Maiores" : "Menores"}</button>
            ))}
          </div>
        )}
      </header>
      {error && <p role="alert" className="p-3 text-sm text-danger">{error}</p>}
      {!ready && !error && <p role="status" className="p-3 text-sm text-muted">Carregando ranking…</p>}
      {ready && rows.length === 0 && <p className="p-3 text-sm text-muted">Nenhum território com dado neste recorte.</p>}
      <ol className="min-h-0 flex-1 overflow-auto py-1">{rows.map((r) => item(r, pos(r)))}</ol>
      {pinned.length > 0 && (
        <ol className="max-h-32 overflow-auto border-t border-line py-1" aria-label="Territórios selecionados fora da lista">{pinned.map((r) => item(r, r.rank, true))}</ol>
      )}
      {ready && (
        <p className="border-t border-line px-3 py-2 text-[11px] leading-snug text-muted">
          {total > LIMIT ? `${LIMIT} ${order === "desc" ? "maiores" : "menores"} de ${fmtNum(total, 0)} com dado` : `${fmtNum(total, 0)} territórios com dado`}
          {missing > 0 ? `; ${fmtNum(missing, 0)} sem dado ficam fora` : ""}. Barra proporcional ao valor{hasNegative ? " absoluto (há valores negativos)" : ""}, em escala linear; cor igual à do mapa. Clique para selecionar ou desmarcar.
        </p>
      )}
    </aside>
  );
}
