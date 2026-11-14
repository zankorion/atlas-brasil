"use client";
import Link from "next/link";
import { useMoney } from "@/lib/money";
import { useCallback } from "react";
import { Chart, type Theme } from "@/components/Chart";
import { useCatalog } from "@/components/pickers";
import { Card, Notice, Stat } from "@/components/ui";
import { useApi, type VarMeta, qs } from "@/lib/api";
import { lineOption, type Serie } from "@/lib/charts";
import { fmtNum } from "@/lib/format";

type Resp = { meta: VarMeta; series: Serie[] };

function Mini({ spec, codes = "BR", title, note }: { spec: string; codes?: string; title: string; note: string }) {
  const [money] = useMoney();
  const { data, error } = useApi<Resp>(`/api/series${qs({ var: spec, codes, real: money })}`);
  const build = useCallback((t: Theme) => {
    if (!data) return {};
    const o = lineOption(t, data.series, data.meta, "nivel");
    return { ...o, legend: { show: false }, grid: { left: 4, right: 10, top: 10, bottom: 4, containLabel: true } };
  }, [data]);
  return (
    <Card title={title}>
      {error ? <Notice kind="error">{error}</Notice> : <Chart build={build} height={190} renderer="svg" ariaLabel={title} />}
      <p className="mt-2 text-xs leading-relaxed text-muted">{note}</p>
      <Link href={`/series?var=${spec}${data?.meta.frequency === "M" ? "&freq=M" : ""}`} className="mt-1 inline-block text-xs text-accent underline">Abrir série completa</Link>
    </Card>
  );
}

const SECTIONS = [
  { href: "/atlas", t: "Explorar", d: "Mapa dos 5.570 municípios com ranking, linha do tempo e variação entre períodos. Selecione um território para abrir o perfil; dois ou mais para compará-los." },
  { href: "/atlas?var=part_credito_coop&level=UF", t: "Cooperativas de crédito", d: "Onde o crédito cooperativo pesa mais — e onde, por isso, a estatística bancária subestima o sistema financeiro local." },
  { href: "/laboratorio", t: "Laboratório Econômico", d: "Dispersão, correlação, regressão, desigualdade territorial, rankings e construtor de indicadores — sem programar." },
  { href: "/series", t: "Séries Históricas", d: "Evolução anual e mensal desde 1994, em valores nominais ou deflacionados pelo IPCA." },
  { href: "/fontes", t: "Fontes e Metodologia", d: "Origem de cada dado, histórico de cargas, regras de cálculo e limitações conhecidas." },
];
const STATUS: Record<string, string> = { mvp: "Disponível", parcial: "Parcial", planejado: "Planejado" };

export default function HomeView() {
  const { meta, error } = useCatalog();
  return (
    <div>
      <section className="border-b border-line">
        <div className="mx-auto grid max-w-7xl gap-8 px-4 py-10 lg:grid-cols-[1.25fr_1fr] lg:py-14">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-accent">Plataforma pública de inteligência econômica e territorial</p>
            <h1 className="mt-3 font-serif text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl">
              Como o Brasil chegou à sua configuração econômica desde o Plano Real
            </h1>
            <p className="mt-4 max-w-2xl text-lg leading-relaxed text-muted">
              Dados públicos oficiais do IBGE e do Banco Central, integrados por município, com fonte, período, unidade e
              metodologia sempre visíveis: economia produtiva, sistema monetário e financeiro, patrimônio, demografia,
              trabalho e renda, educação e saneamento.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/atlas" className="rounded bg-accent px-4 py-2.5 text-sm font-medium text-accent-ink">Explorar o mapa</Link>
              <Link href="/atlas?var=icr" className="rounded border border-line bg-surface px-4 py-2.5 text-sm">Crédito sobre depósitos (ICR) por município</Link>
              <Link href="/laboratorio" className="rounded border border-line bg-surface px-4 py-2.5 text-sm">Abrir o laboratório</Link>
            </div>
          </div>
          <div className="grid content-start gap-5 rounded-md border border-line bg-surface p-5 sm:grid-cols-2">
            {error && <div className="sm:col-span-2"><Notice kind="error">{error}</Notice></div>}
            <Stat label="Indicadores com dados" value={meta ? String(meta.indicators.disponivel ?? 0) : "—"} sub={meta ? `${meta.indicators.planejado ?? 0} catalogados sem dados (planejados)` : undefined} />
            <Stat label="Observações vigentes" value={meta ? fmtNum(meta.counts.observations, 0) : "—"} sub="todas com fonte e versão" />
            <Stat label="Unidades territoriais" value={meta ? fmtNum(meta.counts.territories, 0) : "—"} sub="códigos oficiais do IBGE" />
            <Stat label="Última carga" value={meta?.updated_at ? meta.updated_at.slice(0, 10).split("-").reverse().join("/") : "—"} sub={<Link className="underline" href="/fontes#cargas">histórico de atualizações</Link>} />
            <p className="text-xs leading-relaxed text-muted sm:col-span-2">
              Nenhum número exibido é simulado. Quando uma série não existe para um território ou período, o Atlas mostra a ausência.
            </p>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 py-8">
        <h2 className="font-serif text-2xl font-semibold">O Brasil desde 1994, em três séries</h2>
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          <Mini spec="selic" title="Taxa Selic (% a.a.)" note="Selic acumulada no mês, anualizada. Fonte: Banco Central (SGS 4189)." />
          <Mini spec="credito_sfn_pib" title="Crédito do SFN em relação ao PIB (%)" note="Saldo total da carteira de crédito do Sistema Financeiro Nacional. Fonte: Banco Central (SGS 20622)." />
          <Mini spec="icr" title="Índice de Crédito sobre Depósitos — Brasil (%)" note="Crédito ÷ depósitos nas agências bancárias (ESTBAN, dezembro). Não cobre cooperativas; ver metodologia." />
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-4 pb-8">
        <h2 className="font-serif text-2xl font-semibold">Ferramentas</h2>
        <ul className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SECTIONS.map((s) => (
            <li key={s.href}>
              <Link href={s.href} className="block h-full rounded-md border border-line bg-surface p-4 hover:border-accent">
                <span className="font-serif text-lg font-semibold">{s.t}</span>
                <span className="mt-1 block text-sm leading-relaxed text-muted">{s.d}</span>
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <section className="mx-auto max-w-7xl px-4 pb-12">
        <h2 className="font-serif text-2xl font-semibold">Dimensões do Atlas</h2>
        <p className="mt-1 max-w-3xl text-sm text-muted">O projeto prevê onze dimensões. A cobertura cresce por etapas; o estado atual de cada uma é informado abaixo.</p>
        <ul className="mt-4 grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
          {(meta?.dimensions ?? []).map((d, i) => (
            <li key={d.id} className="flex items-baseline justify-between gap-3 border-b border-line py-2 text-sm">
              <span><span className="num mr-2 text-muted">{String(i + 1).padStart(2, "0")}</span>{d.name}</span>
              <span className={`text-xs uppercase tracking-wide ${d.status === "planejado" ? "text-muted" : "text-accent"}`}>{STATUS[d.status] ?? d.status}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
