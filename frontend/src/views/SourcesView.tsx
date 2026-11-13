"use client";
import { Card, Loading, Markdown, Notice, Page } from "@/components/ui";
import { API, useApi } from "@/lib/api";

type Ds = { id: string; name: string; endpoint: string | null; format: string | null; access: string | null; periodicity: string | null; coverage: string | null; notes: string | null; status: string; indicators: number; publication: string | null; updated_at: string | null };
type Src = { id: string; name: string; url: string | null; license: string | null; notes: string | null; datasets: Ds[] };
type Meth = { id: string; title: string; body: string; version: string };
type Run = { id: number; pipeline: string; dataset_id: string | null; status: string; publication: string | null; started_at: string; finished_at: string | null; rows_new: number; rows_revised: number; rows_unchanged: number; error: string | null };

const RULES = [
  "Dados ausentes nunca são substituídos por zero: aparecem como “sem dado”, em cinza nos mapas e vazios nas exportações.",
  "Valores nominais e reais são sempre distinguidos; o deflacionamento usa o IPCA e informa o período-base.",
  "Revisões das fontes são preservadas: um valor alterado gera nova versão e o anterior permanece no banco.",
  "Mudanças metodológicas e de limites municipais são sinalizadas nas séries, perfis e comparações históricas.",
  "Indicadores derivados e estimados trazem fórmula e método; nada é estimado sem metodologia publicada.",
  "Operações entre unidades incompatíveis são bloqueadas pelo construtor de indicadores.",
  "Periodicidades diferentes (anual × mensal) não são combinadas automaticamente.",
  "Correlações e regressões são associações entre agregados territoriais — não causalidade, nem comportamento individual.",
];

export default function SourcesView() {
  const src = useApi<Src[]>("/api/sources");
  const meth = useApi<Meth[]>("/api/methodologies");
  const runs = useApi<Run[]>("/api/runs?limit=30");
  const fmt = (s: string | null) => (s ? s.replace("T", " ").slice(0, 16) : "—");
  return (
    <Page title="Fontes e Metodologia" lead="De onde vem cada dado, como é transformado e quais são seus limites. Toda observação do Atlas é rastreável até a base oficial e a carga que a registrou.">
      <nav aria-label="Seções" className="mb-6 flex flex-wrap gap-4 text-sm">
        <a className="text-accent underline" href="#regras">Regras metodológicas</a><a className="text-accent underline" href="#fontes">Fontes e bases</a>
        <a className="text-accent underline" href="#metodologias">Metodologias</a><a className="text-accent underline" href="#cargas">Histórico de cargas</a>
        <a className="text-accent underline" href={`${API}/docs`}>Documentação da API (OpenAPI)</a>
      </nav>

      <section id="regras" className="scroll-mt-20">
        <h2 className="font-serif text-2xl font-semibold">Regras metodológicas</h2>
        <ol className="mt-3 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
          {RULES.map((r, i) => <li key={i} className="flex gap-3 border-b border-line py-2"><span className="num text-muted">{String(i + 1).padStart(2, "0")}</span><span>{r}</span></li>)}
        </ol>
      </section>

      <section id="fontes" className="mt-10 scroll-mt-20">
        <h2 className="font-serif text-2xl font-semibold">Fontes e bases de dados</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">“Integrada” significa que há um conector funcional e dados carregados. “Planejada” indica bases previstas no projeto, ainda sem conector — nenhum dado delas é exibido.</p>
        {src.error && <div className="mt-3"><Notice kind="error">{src.error}</Notice></div>}
        {src.loading && <Loading />}
        <div className="mt-4 space-y-4">
          {(src.data ?? []).map((s) => (
            <Card key={s.id} title={s.name} actions={s.url && <a href={s.url} className="text-xs text-accent underline" rel="noreferrer" target="_blank">{s.url.replace(/^https?:\/\//, "")}</a>}>
              {s.license && <p className="mb-3 text-xs text-muted">Licença/condições: {s.license}</p>}
              {s.notes && <p className="mb-3 text-sm text-muted">{s.notes}</p>}
              <ul className="space-y-3">
                {s.datasets.map((d) => (
                  <li key={d.id} className="border-t border-line pt-3 text-sm first:border-0 first:pt-0">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="font-medium">{d.name}</span>
                      <span className={`rounded-sm border px-1.5 py-px text-[11px] uppercase tracking-wide ${d.status === "integrado" ? "border-accent text-accent" : "border-line text-muted"}`}>{d.status === "integrado" ? "Integrada" : "Planejada"}</span>
                    </div>
                    {d.coverage && <p className="mt-1 text-muted">Cobertura: {d.coverage}</p>}
                    {d.notes && <p className="mt-1 text-muted">{d.notes}</p>}
                    <p className="mt-1 text-xs text-muted">
                      {[d.access && `acesso: ${d.access}`, d.format, d.periodicity, d.indicators ? `${d.indicators} indicador(es)` : null, d.publication && `publicação: ${d.publication}`, d.updated_at && `última carga: ${fmt(d.updated_at)}`].filter(Boolean).join(" · ")}
                    </p>
                    {d.endpoint && <p className="num mt-1 break-all text-xs text-muted">{d.endpoint}</p>}
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      </section>

      <section id="metodologias" className="mt-10 scroll-mt-20">
        <h2 className="font-serif text-2xl font-semibold">Metodologias</h2>
        <div className="mt-4 space-y-4">
          {(meth.data ?? []).map((m) => (
            <div key={m.id} id={`m-${m.id}`} className="scroll-mt-20">
              <Card title={<>{m.title} <span className="font-normal text-muted">· v{m.version}</span></>}><Markdown text={m.body} /></Card>
            </div>
          ))}
        </div>
      </section>

      <section id="cargas" className="mt-10 scroll-mt-20">
        <h2 className="font-serif text-2xl font-semibold">Histórico de cargas</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">Cada execução dos pipelines fica registrada, inclusive as que falharam. “Revisadas” conta observações cujo valor mudou em relação à carga anterior (a versão antiga é preservada).</p>
        <div className="mt-4 overflow-x-auto rounded-md border border-line bg-surface">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-muted">
              <tr><th className="px-3 py-2">#</th><th className="px-3 py-2">Pipeline</th><th className="px-3 py-2">Situação</th><th className="px-3 py-2">Concluída</th><th className="px-3 py-2 text-right">Novas</th><th className="px-3 py-2 text-right">Revisadas</th><th className="px-3 py-2 text-right">Inalteradas</th><th className="px-3 py-2">Publicação / erro</th></tr>
            </thead>
            <tbody>
              {(runs.data ?? []).map((r) => (
                <tr key={r.id} className="border-t border-line align-top">
                  <td className="num px-3 py-1.5">{r.id}</td><td className="px-3 py-1.5">{r.pipeline}</td>
                  <td className={`px-3 py-1.5 ${r.status === "erro" ? "text-danger" : ""}`}>{r.status}</td>
                  <td className="num px-3 py-1.5">{fmt(r.finished_at)}</td>
                  <td className="num px-3 py-1.5 text-right">{r.rows_new.toLocaleString("pt-BR")}</td>
                  <td className="num px-3 py-1.5 text-right">{r.rows_revised.toLocaleString("pt-BR")}</td>
                  <td className="num px-3 py-1.5 text-right">{r.rows_unchanged.toLocaleString("pt-BR")}</td>
                  <td className="px-3 py-1.5 text-xs text-muted">{r.error ?? r.publication ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </Page>
  );
}
