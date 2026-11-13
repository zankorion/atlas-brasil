# Atlas Econômico e Social do Brasil

Plataforma pública e de código aberto para coletar, padronizar, visualizar e analisar dados econômicos,
financeiros e territoriais brasileiros desde o Plano Real, com o município como unidade básica.

**Princípio:** todo número exibido vem de uma fonte oficial, com período, unidade, metodologia e carga
rastreáveis. Dado ausente é mostrado como ausente — nunca como zero. Nada é simulado.

## O que já funciona (v0.1 — MVP)

| Área | Situação |
|---|---|
| Dimensão territorial | 5.571 municípios, 510 regiões imediatas, 133 intermediárias, 27 UFs, 5 regiões, Brasil (API de Localidades e Malhas do IBGE) |
| Economia produtiva | PIB, impostos e VAB por setor (SIDRA 5938, 2002–2023), PIB per capita, participações setoriais |
| Demografia | População (censos 2000/2010/2022 + estimativas), área, densidade, crescimento; urbanização e cor ou raça (censos); índice de envelhecimento, idade mediana e razão de sexo (Censo 2022); nascimentos, óbitos e taxas brutas (Registro Civil, 2003+) |
| Agropecuária | Valor da produção e área colhida das lavouras, com soja, milho, cana e café (PAM, 1995+); rebanho bovino, leite e valor da produção animal (PPM, 1995+) |
| Trabalho e renda | Unidades locais, pessoal ocupado, assalariados, massa salarial e salário médio por município (CEMPRE, 2006+); desocupação, Gini e renda domiciliar per capita por UF (PNAD Contínua, 2012+) |
| Educação e saneamento | Taxa de alfabetização e domicílios com água por rede, esgotamento por rede e lixo coletado (Censo 2022) |
| Sistema financeiro territorial | Crédito (total, empréstimos, financiamentos, rural, imobiliário), depósitos (à vista, poupança, a prazo), agências — ESTBAN, posição de dezembro, **1994–2025**; ICR, crédito e depósitos per capita e sobre o PIB |
| Cooperativas de crédito | Postos de atendimento por município (cadastro do BCB, 2016–2025) e carteira de crédito por UF do tomador, com a participação das cooperativas (SCR.data, 2012–2025) |
| Sistema monetário nacional | Selic, IPCA, INPC, base monetária, M1–M4, crédito do SFN (total, PF, PJ, % do PIB), concessões, inadimplência, spread, câmbio — SGS/BCB, mensal desde jul/1994 |
| Patrimônio | Condição de ocupação dos domicílios (Censos 2010 e 2022), estabelecimentos agropecuários e Gini fundiário estimado (Censo Agro 2017) |
| Ferramentas | **Explorar** (mapa coroplético com escala contínua ou em classes, escala divergente com ponto central, ranking em barras, variação entre dois períodos, dois mapas sincronizados; selecionar um território abre o perfil, dois ou mais abrem a comparação); séries históricas; laboratório (dispersão, Pearson/Spearman, regressão, distribuição e desigualdade, rankings, grupos); construtor de indicadores com validação de unidades; pesquisa avançada; exportação CSV/XLSX/JSON/PNG/SVG com metadados |

São 111 indicadores com dados (75 observados nas fontes, 35 derivados por fórmula, 1 estimado) e cerca de 5,0 milhões de observações.

**Catalogados sem dados (planejados):** Pix por município e bens e direitos do IRPF.
Saúde, finanças públicas, meio ambiente e política seguem sem dados: constam do catálogo de fontes como planejadas e não
exibem nenhum número. Trabalho e renda, educação e habitação têm cobertura parcial, só com fontes do IBGE.

## Arquitetura

```
atlas-brasil/
├── backend/                 Python 3.12+ · FastAPI · SQLAlchemy · Polars
│   ├── atlas/
│   │   ├── catalog/         catálogos versionados em YAML: fontes, bases, unidades, metodologias, indicadores
│   │   ├── connectors/      clientes das fontes oficiais (IBGE Localidades/Malhas/SIDRA/Biblioteca; BCB SGS, ESTBAN, postos e SCR.data)
│   │   ├── pipelines/       cargas: territórios, emancipações, PIB, população, domicílios, censo agro, ESTBAN, cooperativas, SCR, SGS, agregação
│   │   ├── stats/           motor de fórmulas (unidades, ausências, deflacionamento) e estatísticas
│   │   ├── api/             rotas: catálogo, dados (mapa, séries, perfis, exportação) e laboratório
│   │   ├── models.py        modelo relacional
│   │   ├── store.py         gravação versionada de observações + registro de cargas
│   │   └── cli.py           migrate · seed · ingest · status
│   ├── migrations/          Alembic (0001 esquema, 0002 geometria PostGIS)
│   └── tests/               pytest (40 testes)
├── frontend/                Next.js 16 · React 19 · TypeScript · Tailwind 4 · MapLibre GL · ECharts
│   └── src/{app,views,components,lib}
├── data/                    (não versionado) banco SQLite local, cache bruto das fontes, malhas
└── docker-compose.yml       PostgreSQL/PostGIS + API + web
```

### Modelo de dados

- `source`, `dataset` — instituições e bases, com endpoint, licença, cobertura e situação (integrada/planejada).
- `methodology` — textos metodológicos versionados.
- `unit` — unidades com **dimensões** (`{"BRL": 1, "pessoa": -1}`), usadas na validação de fórmulas.
- `indicator` — catálogo: natureza (observado/derivado/estimado), tipo de valor, estoque/fluxo, periodicidade,
  níveis territoriais, fórmula, limitações, quebras metodológicas.
- `territory`, `territory_change` — códigos IBGE em seis níveis e alterações da malha municipal.
- `observation` — indicador × território × período × valor, com `flag` (motivo da ausência ou anotação),
  `revision`/`is_current` (revisões preservadas) e `run_id` (carga de origem).
- `ingestion_run` — histórico de cargas: publicação, parâmetros, contagens (novas/revisadas/inalteradas), erros.
- `saved_view` — reservado para visualizações salvas.

Indicadores **derivados não são armazenados**: são calculados na consulta pelo motor de fórmulas a partir das
observações vigentes, de modo que revisões das fontes se propagam sem recarga.

### Regras metodológicas implementadas

1. Ausente ≠ zero: símbolos do IBGE (`...`, `X`, `..`) viram nulo com motivo; município sem agência no ESTBAN não recebe linha.
2. Nominal × real: `real=true` deflaciona pelo IPCA (média anual para fluxos, dezembro para estoques) e informa a base.
3. Revisões: valor alterado em nova carga gera `revision + 1`; a versão anterior permanece.
4. Quebras metodológicas e alterações territoriais aparecem em séries, perfis e no comparador histórico.
5. Unidades: `R$ + pessoas` é rejeitado; divisões compõem unidades; divisão por zero → ausente (contada).
6. Periodicidades diferentes (anual × mensal) não são combinadas.
7. Agregações só por soma de indicadores aditivos; se um membro está sob sigilo, o agregado fica ausente.
8. Toda resposta da API traz `meta` com fonte, publicação, data de carga, fórmula, notas e limitações.

## Como executar (desenvolvimento local, sem Docker)

Pré-requisitos: Python 3.12+ e Node.js 20+. O banco padrão é um arquivo SQLite em `data/atlas.db`.

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Linux/macOS: .venv/bin/python
.venv/Scripts/python -m atlas.cli migrate
.venv/Scripts/python -m atlas.cli seed
.venv/Scripts/python -m atlas.cli ingest all                 # ~10 min; baixa ~115 MB das fontes oficiais
.venv/Scripts/python -m uvicorn atlas.api.main:app --port 8000
```

```bash
cd frontend
npm install
npm run dev            # http://localhost:3000
```

- API interativa (OpenAPI): http://localhost:8000/docs
- `NEXT_PUBLIC_API_URL` define o endereço da API para o frontend (padrão `http://localhost:8000`).
- Variáveis do backend: ver `.env.example` (prefixo `ATLAS_`).

### Pipelines

```bash
python -m atlas.cli ingest territorios      # localidades e malhas
python -m atlas.cli ingest emancipacoes     # municípios instalados desde 1991 e municípios de origem
python -m atlas.cli ingest sgs              # séries mensais do BCB + índice do IPCA
python -m atlas.cli ingest populacao        # SIDRA 6579, 202, 4714
python -m atlas.cli ingest sidra            # todos os indicadores com origem SIDRA no catálogo (PIB, PAM, PPM, CEMPRE, Registro Civil, Censo 2022, PNADC)
python -m atlas.cli ingest sidra --so ibge_pam   # só uma base (ou um indicador)
python -m atlas.cli ingest domicilios       # SIDRA 3219 e 9930
python -m atlas.cli ingest censo_agro       # SIDRA 6754 + Gini fundiário
python -m atlas.cli ingest estban --inicio 2024   # arquivos de dezembro do ESTBAN
python -m atlas.cli ingest cooperativas     # postos de atendimento de cooperativas (dezembro, 2016+)
python -m atlas.cli ingest scr              # carteira de crédito por UF e tipo de instituição (dezembro, 2012+)
python -m atlas.cli ingest agregacao        # somas para regiões imediatas e intermediárias
python -m atlas.cli status                  # contagens por indicador e últimas cargas
```

As respostas brutas ficam em `data/raw/` (reprodutibilidade e cortesia com os serviços públicos); use `--refresh`
para baixar de novo. As cargas são idempotentes: reexecutar só grava o que é novo ou foi revisado.
Para atualização automática, agende `ingest all` (cron, Agendador de Tarefas ou n8n) — por exemplo, mensalmente.

### Testes

```bash
cd backend && .venv/Scripts/python -m pytest -q
cd frontend && npx tsc --noEmit && npx eslint src && npm run build
```

Os testes usam um SQLite temporário com poucas observações **sintéticas, restritas à suíte de testes**.

## Docker (PostgreSQL + PostGIS)

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec api python -m atlas.cli migrate
docker compose exec api python -m atlas.cli seed
docker compose exec api python -m atlas.cli ingest all
```

> **Aviso:** a composição Docker e o caminho PostgreSQL/PostGIS foram escritos, mas **ainda não foram executados**
> (a máquina de desenvolvimento não tinha Docker). O código de acesso usa apenas SQLAlchemy portável; valide antes
> de usar em produção. Em PostgreSQL, a migração `0002` cria a coluna `territory.geom`; o carregamento das
> geometrias nessa coluna ainda não foi implementado — as malhas são servidas dos arquivos em `data/geo/`.

## Limitações conhecidas desta versão

- **ESTBAN** cobre bancos com carteira comercial e caixas econômicas; cooperativas de crédito, financeiras e
  fintechs não constam, e os saldos são localizados pela agência, não pelo domicílio do cliente. O ICR deve ser lido
  com essa ressalva (ver metodologia na aplicação).
- **Série anual do ESTBAN** usa só a posição de dezembro; os demais meses ainda não são carregados.
- **População**: mistura censos e estimativas; não há dado para 1995–1999, 2007 e 2023, o que deixa indicadores
  per capita ausentes nesses anos.
- **Registro Civil**: as tabelas de nascimentos e óbitos respondem devagar no servidor do IBGE (cerca de um minuto por ano); a
  carga completa leva uns 40 minutos. Os números dependem do registro em cartório e têm sub-registro.
- **CEMPRE**: troca de tabela em 2022 (salto de 55 para 63 milhões de pessoas ocupadas); cobre só organizações formais.
- **PNAD Contínua**: só Brasil, regiões e UFs; é amostral e o Atlas não exibe o erro de amostragem.
- **Participações** (setoriais, de crédito, de soja): onde a fonte traz parcela negativa ou maior que o total, o valor fica ausente.
- **PIB real municipal** não existe na fonte; a opção "valores reais" aplica o IPCA nacional.
- **VAB setorial de 2022–2023** consta como não disponível na própria tabela do IBGE.
- **Alterações territoriais**: 1.080 municípios instalados desde 1991 estão registrados (483 em 1993, 533 em 1997, 53 em 2001
  e 11 desde 2005). O ano é inferido da primeira publicação de população do IBGE em que o município aparece. O município de
  origem foi identificado automaticamente em 527 casos; nos outros 553 ele não é conhecido, e o município que cedeu área
  não recebe o aviso. Não há áreas mínimas comparáveis.
- **Cooperativas de crédito**: não existe base pública de saldos por município. Os postos de atendimento medem presença
  física, não volume, e a série só é confiável de 2016 em diante; o crédito das cooperativas existe apenas por UF (SCR.data),
  localizado pelo tomador, e não é somável ao ESTBAN. Depósitos em cooperativas por território seguem sem fonte. Em dez/2025 a
  fonte publicou o SCR.data sem o tipo de instituição: a participação das cooperativas fica ausente nesse ano.
- **Gini fundiário** é estimativa por dados agrupados com imputação residual das áreas sob sigilo.
- Regiões metropolitanas não estão integradas; regiões imediatas/intermediárias recebem apenas indicadores aditivos somados.
- Componentes de interface seguem o estilo shadcn/ui, mas foram escritos à mão (a CLI do shadcn não foi usada).
- Mapas usam GeoJSON generalizado servido pela API (≈ 1 MB comprimido para municípios), sem tiles vetoriais.
- Sem autenticação, limite de requisições ou cache HTTP — a API ainda não está pronta para exposição pública.

## Próximos passos (roadmap)

1. Pix por município (BCB); série mensal completa do ESTBAN; conferência manual das origens das emancipações.
2. Finanças públicas municipais (SICONFI), emprego formal (RAIS/CAGED) e saúde (DATASUS).
3. Dimensão eleitoral (TSE) com documentação de mudanças partidárias.
4. Áreas mínimas comparáveis.
5. Modelos em painel e autocorrelação espacial (Moran) no laboratório.
6. Validação do caminho PostgreSQL/PostGIS, tiles vetoriais e API pública com controle de uso.

## Licença dos dados

Os dados pertencem às instituições de origem (IBGE; Banco Central — ODbL). Cite sempre a fonte original indicada
em cada indicador e exportação.
