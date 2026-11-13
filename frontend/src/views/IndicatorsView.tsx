"use client";
import Link from "next/link";
import { useState } from "react";
import { useCatalog } from "@/components/pickers";
import { Field, Loading, NatureTag, Notice, Page, Select, inputCls } from "@/components/ui";
import { periodLabel } from "@/lib/format";

export default function IndicatorsView() {
  const { indicators, dimensions, error, loading } = useCatalog();
  const [dim, setDim] = useState("");
  const [nature, setNature] = useState("");
  const [q, setQ] = useState("");
  const norm = (s: string) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const list = indicators.filter((i) => (!dim || i.dimension === dim) && (!nature || (nature === "planejado" ? i.status === "planejado" : i.nature === nature && i.status !== "planejado"))
    && (!q || norm(i.name + " " + (i.description ?? "")).includes(norm(q))));
  return (
    <Page title="Indicadores" lead="Catálogo de indicadores do Atlas. Cada indicador informa unidade, natureza (observado, derivado ou estimado), cobertura temporal efetiva, fonte e limitações.">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Buscar"><input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Nome ou descrição" /></Field>
        <Field label="Dimensão">
          <Select value={dim} onChange={setDim} options={[{ value: "", label: "Todas" }, ...dimensions.map((d) => ({ value: d.id, label: d.name }))]} />
        </Field>
        <Field label="Natureza">
          <Select value={nature} onChange={setNature} options={[{ value: "", label: "Todas" }, { value: "observado", label: "Observado (publicado pela fonte)" },
            { value: "derivado", label: "Derivado (fórmula do Atlas)" }, { value: "estimado", label: "Estimado (método próprio)" }, { value: "planejado", label: "Planejado (sem dados)" }]} />
        </Field>
      </div>
      {error && <div className="mt-4"><Notice kind="error">{error}</Notice></div>}
      {loading && <Loading />}
      {dimensions.map((d) => {
        const items = list.filter((i) => i.dimension === d.id);
        if (!items.length) return null;
        return (
          <section key={d.id} className="mt-8">
            <h2 className="font-serif text-xl font-semibold">{d.name}</h2>
            <div className="mt-2 overflow-x-auto rounded-md border border-line bg-surface">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="text-left text-xs uppercase tracking-wide text-muted">
                  <tr><th className="px-3 py-2">Indicador</th><th className="px-3 py-2">Unidade</th><th className="px-3 py-2">Natureza</th><th className="px-3 py-2">Cobertura</th><th className="px-3 py-2">Fonte</th></tr>
                </thead>
                <tbody>
                  {items.map((i) => (
                    <tr key={i.id} className="border-t border-line align-top">
                      <td className="px-3 py-2">
                        <Link href={`/indicadores/${i.id}`} className="font-medium text-accent underline-offset-2 hover:underline">{i.name}</Link>
                        <div className="num text-xs text-muted">{i.id}</div>
                      </td>
                      <td className="px-3 py-2">{i.unit}</td>
                      <td className="px-3 py-2">{i.status === "planejado" ? <span className="text-xs uppercase tracking-wide text-muted">Planejado</span> : <NatureTag nature={i.nature} />}</td>
                      <td className="num px-3 py-2">
                        {i.status === "planejado" ? <span className="font-sans text-muted">sem dados integrados</span>
                          : i.period_min ? `${periodLabel(i.period_min)} – ${periodLabel(i.period_max)}` : "—"}
                        {i.status !== "planejado" && <div className="font-sans text-xs text-muted">{i.frequency === "M" ? "mensal · Brasil" : `anual · ${i.n_periods ?? 0} períodos`}</div>}
                      </td>
                      <td className="px-3 py-2 text-muted">{i.source ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}
      {!loading && list.length === 0 && <div className="mt-6"><Notice>Nenhum indicador corresponde aos filtros.</Notice></div>}
    </Page>
  );
}
