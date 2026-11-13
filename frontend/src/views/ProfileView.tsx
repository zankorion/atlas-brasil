"use client";
import Link from "next/link";
import { useCallback, useState } from "react";
import { Chart, type Theme } from "@/components/Chart";
import { IndicatorSelect, useCatalog } from "@/components/pickers";
import { Card, Check, Loading, NatureTag, Notice, Provenance } from "@/components/ui";
import { API, qs, useApi, type VarMeta } from "@/lib/api";
import { lineOption, type Serie, type Transform } from "@/lib/charts";
import { fmtNum, fmtValue, LEVEL_SINGULAR, periodLabel } from "@/lib/format";

type Terr = {
  code: string; level: string; name: string; uf: string | null; uf_code: string | null;
  parents: { code: string; level: string; level_name: string; name: string }[];
  changes: { kind: string; year: number; note: string; related: { code: string; name: string }[] }[];
  first_population_year: string | null; n_municipios?: number;
};
type Row = {
  id: string; name: string; short_name: string; dimension: string; unit: string; decimals: number; nature: string; percent: boolean;
  period: string | null; value: number | null; rank?: number | null; rank_of?: number | null; uf_value?: number | null;
  br_value?: number | null; first_period?: string; stale?: boolean; missing_reason?: string;
};
type Similar = { basis: string | null; period?: string; items: { code: string; name: string; uf: string; populacao: number; pib_per_capita: number }[] };

function Evolution({ t }: { t: Terr }) {
  const [spec, setSpec] = useState(t.level === "BR" ? "pib_nominal" : "pib_per_capita");
  const [real, setReal] = useState(true);
  const [idx, setIdx] = useState(false);
  const codes = [t.code, ...(t.level === "MUN" && t.uf_code ? [t.uf_code] : []), ...(t.level !== "BR" ? ["BR"] : [])].join(",");
  const { data, error } = useApi<{ meta: VarMeta; series: Serie[]; territory_changes: { year: number; note: string }[] }>(`/api/series${qs({ var: spec, codes, real })}`);
  const transform: Transform = idx ? "indice" : "nivel";
  const build = useCallback((th: Theme) => (data ? lineOption(th, data.series, data.meta, transform,
    data.territory_changes.map((c) => ({ period: String(c.year), label: "alteração territorial" }))) : {}), [data, transform]);
  return (
    <Card title="Evolução histórica — comparação com o estado e o Brasil">
      <div className="mb-3 grid gap-3 sm:grid-cols-[1fr_auto_auto] sm:items-end">
        <IndicatorSelect value={spec} onChange={setSpec} level={t.level} frequency="A" />
        <Check checked={real} onChange={setReal} label="Valores reais (IPCA)" />
        <Check checked={idx} onChange={setIdx} label="Base 100 (ritmo de crescimento)" />
      </div>
      {error ? <Notice kind="error">{error}</Notice> : <Chart build={build} height={340} renderer="svg" exportName={`atlas_${t.code}_${spec.replace(/\W/g, "")}`} ariaLabel="Evolução histórica" />}
      {data && <div className="mt-3"><Provenance meta={data.meta} /></div>}
    </Card>
  );
}

/** Perfil completo de um território, exibido no Explorar quando há um único território selecionado. */
export function ProfileBody({ code }: { code: string }) {
  const { dimensions } = useCatalog();
  const terr = useApi<Terr>(`/api/territories/${code}`);
  const prof = useApi<{ indicators: Row[] }>(`/api/profile/${code}`);
  const sim = useApi<Similar>(`/api/similar/${code}`);
  if (terr.error) return <Notice kind="error">{terr.error}</Notice>;
  const t = terr.data;
  if (!t || t.code !== code) return <Loading label="Carregando perfil…" />;
  const rows = prof.data?.indicators ?? [];
  const get = (id: string) => rows.find((r) => r.id === id);
  const key = ["populacao", "pib_nominal", "pib_per_capita", "credito_total", "depositos_total", "icr"].map(get).filter(Boolean) as Row[];
  const isMun = t.level === "MUN";
  const showUf = ["MUN", "RGI", "RGINT"].includes(t.level);
  const estbanMissing = isMun && rows.some((r) => r.id === "credito_total" && r.value === null);
  return (
    <section aria-label={`Perfil de ${t.name}`}>
      <h2 className="font-serif text-2xl font-semibold tracking-tight">Perfil — {t.name}{isMun && t.uf ? ` — ${t.uf}` : ""}</h2>
      <nav aria-label="Hierarquia territorial" className="mb-5 mt-1 flex flex-wrap items-center gap-x-2 text-sm text-muted">
        <span className="rounded-sm border border-line px-1.5 py-px text-[11px] uppercase tracking-wide">{LEVEL_SINGULAR[t.level]}</span>
        <span className="num">IBGE {t.code}</span>
        {[...t.parents].reverse().map((p) => <span key={p.code}>· <Link className="text-accent underline" href={`/territorios/${p.code}`}>{p.name}</Link></span>)}
        {t.n_municipios ? <span>· {t.n_municipios} municípios</span> : null}
      </nav>

      {t.changes.map((c) => (
        <div key={c.kind + c.year} className="mb-3">
          <Notice kind="warn"><strong>Alteração territorial em {c.year}.</strong> {c.note} Séries anteriores e posteriores a essa data referem-se a áreas diferentes e não são diretamente comparáveis.</Notice>
        </div>
      ))}
      {isMun && t.first_population_year && Number(t.first_population_year) > 2000 && t.changes.length === 0 && (
        <div className="mb-3"><Notice kind="warn">As séries deste município começam em {t.first_population_year}: ele pode ter sido instalado após 2000 e não constar ainda da tabela de alterações territoriais do Atlas.</Notice></div>
      )}

      {prof.error && <Notice kind="error">{prof.error}</Notice>}
      {prof.loading && !prof.data && <Loading label="Calculando indicadores e posições…" />}

      {key.length > 0 && (
        <section aria-label="Síntese" className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line md:grid-cols-3 xl:grid-cols-6">
          {key.map((r) => (
            <div key={r.id} className="bg-surface p-4">
              <div className="text-xs uppercase tracking-wide text-muted">{r.short_name}</div>
              <div className="num mt-1 text-xl font-medium">{r.value === null ? "Sem dado" : fmtValue(r.value, r)}</div>
              <div className="mt-0.5 text-xs text-muted">{r.period ? `ref. ${periodLabel(r.period)}` : "ausente nesta base"}{r.rank ? ` · ${r.rank}º de ${fmtNum(r.rank_of, 0)}` : ""}</div>
            </div>
          ))}
        </section>
      )}
      {estbanMissing && <div className="mt-3"><Notice>Este município não aparece no ESTBAN: não possui agência de banco comercial ou caixa econômica que reporte ao Banco Central. Crédito, depósitos e ICR ficam ausentes (não são zero) — cooperativas e correspondentes não são cobertos por essa base.</Notice></div>}

      <div className="mt-6 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-5">
          <Evolution key={t.code} t={t} />
          {dimensions.map((d) => {
            const items = rows.filter((r) => r.dimension === d.id);
            if (!items.length) return null;
            return (
              <Card key={d.id} title={d.name}>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-sm">
                    <thead className="text-left text-xs uppercase tracking-wide text-muted">
                      <tr>
                        <th className="py-1.5 pr-3">Indicador</th><th className="px-3 py-1.5 text-right">Valor</th><th className="px-3 py-1.5">Ref.</th>
                        {showUf && <th className="px-3 py-1.5 text-right">{t.uf ?? "UF"}</th>}
                        {t.level !== "BR" && <th className="px-3 py-1.5 text-right">Brasil</th>}
                        {t.level !== "BR" && <th className="py-1.5 pl-3 text-right">Posição</th>}
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((r) => (
                        <tr key={r.id} className="border-t border-line">
                          <td className="py-1.5 pr-3">
                            <Link href={`/indicadores/${r.id}`} className="hover:text-accent hover:underline">{r.name}</Link>{" "}
                            {r.nature !== "observado" && <NatureTag nature={r.nature} />}
                            <div className="text-xs text-muted">{r.unit}</div>
                          </td>
                          <td className="num px-3 py-1.5 text-right">{r.value === null ? <span className="font-sans text-muted" title={r.missing_reason}>sem dado</span> : fmtValue(r.value, r, { unit: false })}</td>
                          <td className="num px-3 py-1.5 text-muted">{periodLabel(r.period)}{r.stale && <span title="Há períodos mais recentes do indicador sem dado para este território" className="text-warn"> *</span>}</td>
                          {showUf && <td className="num px-3 py-1.5 text-right text-muted">{fmtValue(r.uf_value, r, { unit: false })}</td>}
                          {t.level !== "BR" && <td className="num px-3 py-1.5 text-right text-muted">{fmtValue(r.br_value, r, { unit: false })}</td>}
                          {t.level !== "BR" && <td className="num py-1.5 pl-3 text-right text-muted">{r.rank ? `${r.rank}º / ${fmtNum(r.rank_of, 0)}` : "—"}</td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>
            );
          })}
          {rows.length > 0 && (
            <p className="text-xs leading-relaxed text-muted">
              Cada valor refere-se ao período indicado em “Ref.” — o mais recente com dado para este território. Colunas de comparação usam o mesmo período.
              “Posição” ordena do maior para o menor valor entre os territórios do mesmo nível com dado; não implica juízo de melhor ou pior.
              Resultados eleitorais e demais dimensões sociais ainda não estão integrados.
            </p>
          )}
        </div>
        <aside className="min-w-0 space-y-5">
          <Card title="Ações">
            <div className="flex flex-col gap-2 text-sm">
              <Link className="rounded border border-line px-3 py-2 hover:border-accent" href={`/atlas?codes=${t.code}${t.uf_code && isMun ? "," + t.uf_code : ""}${t.level !== "BR" ? ",BR" : ""}`}>Comparar com o estado e o Brasil</Link>
              <Link className="rounded border border-line px-3 py-2 hover:border-accent" href={`/series?codes=${t.code}`}>Abrir séries históricas</Link>
              
              {rows.length > 0 && <a className="rounded border border-line px-3 py-2 hover:border-accent" href={`${API}/api/export${qs({ vars: rows.filter((r) => r.value !== null).slice(0, 10).map((r) => r.id).join(";"), level: t.level, codes: t.code, format: "xlsx" })}`}>Baixar séries (XLSX, 10 primeiros indicadores)</a>}
            </div>
          </Card>
          {t.level !== "BR" && (
            <Card title={`${isMun ? "Municípios" : "Territórios"} semelhantes`}>
              {sim.loading && <Loading />}
              {sim.data && sim.data.items.length === 0 && <p className="text-sm text-muted">Sem dados suficientes para calcular semelhança.</p>}
              {sim.data && sim.data.items.length > 0 && (
                <>
                  <ul className="text-sm">
                    {sim.data.items.map((s) => (
                      <li key={s.code} className="flex items-baseline justify-between gap-2 border-b border-line py-1.5">
                        <Link href={`/territorios/${s.code}`} className="hover:text-accent hover:underline">{s.name}{isMun ? ` (${s.uf})` : ""}</Link>
                        <span className="num shrink-0 text-xs text-muted">{fmtNum(s.populacao, 0)} hab. · R$ {fmtNum(s.pib_per_capita, 0)}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 text-xs leading-relaxed text-muted">{sim.data.basis}</p>
                  <Link className="mt-2 inline-block text-sm text-accent underline" href={`/atlas?codes=${[t.code, ...sim.data.items.slice(0, 4).map((s) => s.code)].join(",")}`}>Comparar com os semelhantes</Link>
                </>
              )}
            </Card>
          )}
        </aside>
      </div>
    </section>
  );
}
