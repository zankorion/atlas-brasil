"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Card, Loading, Markdown, NatureTag, Notice, Page } from "@/components/ui";
import { useApi, type Indicator, type SourceRef } from "@/lib/api";
import { periodLabel } from "@/lib/format";

type Detail = Indicator & {
  methodology: { id: string; title: string; body: string; version: string } | null;
  coverage: { level: string; level_name: string; period_min: string; period_max: string; n_periods: number; periods: string[] }[];
  components?: { id: string; name: string }[]; sources?: SourceRef[]; revisions?: number;
};
const KIND: Record<string, string> = { nominal: "Valor monetário nominal (preços correntes)", quantidade: "Quantidade", razao: "Razão", taxa: "Taxa", indice: "Índice" };

export default function IndicatorDetailView() {
  const { id } = useParams<{ id: string }>();
  const { data: d, error, loading } = useApi<Detail>(`/api/indicators/${id}`);
  if (error) return <Page title="Indicador"><Notice kind="error">{error}</Notice></Page>;
  if (!d || loading) return <Page title="Indicador"><Loading /></Page>;
  const planned = d.status === "planejado";
  return (
    <Page title={d.name} lead={d.description ?? undefined}>
      <p className="-mt-3 mb-5 flex flex-wrap items-center gap-3 text-sm text-muted">
        <Link href="/indicadores" className="text-accent underline">← Indicadores</Link>
        <span className="num">{d.id}</span>
        {planned ? <span className="text-xs uppercase tracking-wide">Planejado</span> : <NatureTag nature={d.nature} />}
      </p>
      {planned && <div className="mb-5"><Notice kind="warn">Este indicador está catalogado, mas ainda não possui dados integrados. Nenhum valor é exibido para ele.</Notice></div>}
      <div className="grid gap-5 lg:grid-cols-[1fr_22rem]">
        <div className="space-y-5">
          <Card title="Ficha técnica">
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <div><dt className="text-xs uppercase tracking-wide text-muted">Unidade</dt><dd>{d.unit}</dd></div>
              <div><dt className="text-xs uppercase tracking-wide text-muted">Tipo de valor</dt><dd>{KIND[d.value_kind] ?? d.value_kind}</dd></div>
              <div><dt className="text-xs uppercase tracking-wide text-muted">Periodicidade</dt><dd>{d.frequency === "M" ? "Mensal" : "Anual"}{d.stock_flow === "estoque" ? " · estoque (fim de período)" : d.stock_flow === "fluxo" ? " · fluxo" : ""}</dd></div>
              <div><dt className="text-xs uppercase tracking-wide text-muted">Base de dados</dt><dd>{d.source ? `${d.source} — ${d.dataset}` : "—"}</dd></div>
              {d.formula && <div className="sm:col-span-2"><dt className="text-xs uppercase tracking-wide text-muted">Fórmula</dt><dd><code className="num rounded bg-surface-2 px-1.5 py-0.5">{d.formula}</code></dd></div>}
              {d.components && d.components.length > 0 && (
                <div className="sm:col-span-2"><dt className="text-xs uppercase tracking-wide text-muted">Componentes</dt>
                  <dd className="flex flex-wrap gap-x-4">{d.components.map((c) => <Link key={c.id} href={`/indicadores/${c.id}`} className="text-accent underline">{c.name}</Link>)}</dd></div>
              )}
              {typeof d.revisions === "number" && <div><dt className="text-xs uppercase tracking-wide text-muted">Revisões preservadas</dt><dd className="num">{d.revisions} observações substituídas</dd></div>}
            </dl>
          </Card>
          {d.limitations && <Notice kind="warn"><strong>Limitações.</strong> {d.limitations}</Notice>}
          {d.breaks.length > 0 && (
            <Card title="Quebras metodológicas">
              <ul className="space-y-1 text-sm">{d.breaks.map((b) => <li key={b.period}><span className="num font-medium">{b.period}</span> — {b.note}</li>)}</ul>
            </Card>
          )}
          {d.methodology && <Card title={`Metodologia — ${d.methodology.title} (v${d.methodology.version})`}><Markdown text={d.methodology.body} /></Card>}
        </div>
        <div className="space-y-5">
          {!planned && (
            <Card title="Explorar">
              <div className="flex flex-col gap-2 text-sm">
                {d.frequency === "A" && <Link className="rounded border border-line px-3 py-2 hover:border-accent" href={`/atlas?var=${d.id}${d.levels.includes("MUN") ? "" : "&level=UF"}`}>Ver no mapa</Link>}
                <Link className="rounded border border-line px-3 py-2 hover:border-accent" href={`/series?var=${d.id}${d.frequency === "M" ? "&freq=M" : ""}`}>Série histórica</Link>
                {d.frequency === "A" && <Link className="rounded border border-line px-3 py-2 hover:border-accent" href={`/laboratorio?tab=ranking&var=${d.id}`}>Ranking e distribuição</Link>}
              </div>
            </Card>
          )}
          <Card title="Cobertura efetiva">
            {d.coverage.length === 0 ? <p className="text-sm text-muted">Sem dados.</p> : (
              <table className="w-full text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted"><tr><th className="py-1">Nível</th><th className="py-1">Período</th><th className="py-1 text-right">Nº</th></tr></thead>
                <tbody>{d.coverage.map((c) => (
                  <tr key={c.level} className="border-t border-line"><td className="py-1.5">{c.level_name}</td>
                    <td className="num py-1.5">{periodLabel(c.period_min)} – {periodLabel(c.period_max)}</td><td className="num py-1.5 text-right">{c.n_periods}</td></tr>
                ))}</tbody>
              </table>
            )}
            {d.coverage[0] && d.frequency === "A" && (
              <p className="mt-3 text-xs leading-relaxed text-muted">Anos com dados ({d.coverage[0].level_name.toLowerCase()}): <span className="num">{d.coverage[0].periods.join(", ")}</span>. Demais anos estão ausentes na fonte.</p>
            )}
          </Card>
          {d.sources && d.sources.length > 0 && (
            <Card title="Fontes e atualização">
              <ul className="space-y-3 text-sm">{d.sources.map((s) => (
                <li key={s.dataset_id}>
                  <div className="font-medium">{s.source}</div><div>{s.dataset}</div>
                  {s.publication && <div className="text-xs text-muted">Publicação: {s.publication}</div>}
                  {s.updated_at && <div className="text-xs text-muted">Carga: {s.updated_at.replace("T", " ")}</div>}
                  {s.endpoint && <div className="num break-all text-xs text-muted">{s.endpoint}</div>}
                </li>
              ))}</ul>
            </Card>
          )}
        </div>
      </div>
    </Page>
  );
}
